# Copyright (c) 2023, Avunu LLC and Contributors
# See license.txt

import base64
import json
from typing import cast

import frappe
from frappe.tests import IntegrationTestCase

from espresso_sync.espresso_sync.doctype.espresso_sync_connection.test_espresso_sync_connection import (
	make_connection,
)
from espresso_sync.espresso_sync.doctype.espresso_sync_pull_log.espresso_sync_pull_log import (
	EspressoSyncPullLog,
)
from espresso_sync.redaction import (
	REDACTED,
	redact_pull_log_values,
	redact_request,
	redact_text,
	redact_url,
)

SECRET = "hunter2-secret-value"


def get_pull_log(name) -> EspressoSyncPullLog:
	return cast(EspressoSyncPullLog, frappe.get_doc("Espresso Sync Pull Log", name))


def latest_pull_log(connection_name):
	name = frappe.get_all(
		"Espresso Sync Pull Log",
		filters={"sync_connection": connection_name},
		order_by="creation desc",
		pluck="name",
		limit=1,
	)[0]
	return frappe.get_doc("Espresso Sync Pull Log", name)


def pull_log_text(doc):
	return " ".join(
		str(doc.get(f) or "")
		for f in ("url", "request", "response", "traceback", "object", "document", "map")
	)


class TestRedactionHelper(IntegrationTestCase):
	def test_headers(self):
		request = {
			"payload": None,
			"headers": {
				"Authorization": "Basic dXNlcjpwYXNz",
				"proxy-authorization": "Bearer abc",
				"X-API-Key": "k1",
				"X-Shop-Header": "k2",
				"Content-Type": "application/json",
			},
		}
		redacted = redact_request(request, header_names={"x-shop-header"})
		self.assertEqual(
			redacted["headers"],
			{
				"Authorization": REDACTED,
				"proxy-authorization": REDACTED,
				"X-API-Key": REDACTED,
				"X-Shop-Header": REDACTED,
				"Content-Type": "application/json",
			},
		)
		# the caller's dict is still used for requests: it must not change
		self.assertEqual(request["headers"]["Authorization"], "Basic dXNlcjpwYXNz")
		# JSON text in, JSON text out
		self.assertEqual(json.loads(redact_request(json.dumps(request)))["headers"]["X-API-Key"], REDACTED)

	def test_url(self):
		self.assertEqual(
			redact_url("https://user:pw@api.example.com/v1/x?api_key=abc&page=2&access_token=t"),
			f"https://{REDACTED}@api.example.com/v1/x?api_key={REDACTED}&page=2&access_token={REDACTED}",
		)
		plain = "https://api.example.com/v1/x?page=2"
		self.assertEqual(redact_url(plain), plain)

	def test_text(self):
		text = "{'headers': {'Authorization': 'Basic dXNlcjpwYXNz', 'X-Shop-Header': 'zzz'}} " + SECRET
		redacted = redact_text(text, secrets={SECRET}, header_names={"x-shop-header"})
		self.assertNotIn("dXNlcjpwYXNz", redacted)
		self.assertNotIn("zzz", redacted)
		self.assertNotIn(SECRET, redacted)
		self.assertIn(f"'Authorization': 'Basic {REDACTED}'", redacted)
		# idempotent
		self.assertEqual(redact_text(redacted, {SECRET}, {"x-shop-header"}), redacted)

	def test_names_in_free_text(self):
		# Python repr (an export response), form-encoded payloads, header lines
		text = (
			str({"access_token": "tok-AAAA", "auth": {"user": "u", "password": "pw 777"}, "author": "bob"})
			+ " grant_type=client_credentials&client_secret=cs-555&page=2"
			+ "\nX-Api-Key: zzz"
		)
		redacted = redact_text(text)
		for secret in ("tok-AAAA", "pw 777", "cs-555", "zzz"):
			self.assertNotIn(secret, redacted)
		for kept in ("'author': 'bob'", "'user': 'u'", "grant_type=client_credentials", "page=2"):
			self.assertIn(kept, redacted)
		self.assertEqual(redact_text(redacted), redacted)

	def test_response_traceback_and_object(self):
		echoed = {
			"access_token": "tok-AAAA",
			"client_secret": "cs-123",
			"next": "https://api.example.invalid/v1/o?page=2&api_key=KEYKEY",
			"id": 7,
		}
		values = {
			"response": json.dumps(echoed),
			"object": json.dumps(echoed, indent=4),
			"traceback": ValueError("boom Authorization: Basic dXNlcjpwYXNz"),
			"map": json.dumps({"api_key": "customer.key"}),
		}
		redacted = redact_pull_log_values(values)
		for field in ("response", "object"):
			parsed = json.loads(redacted[field])
			self.assertEqual(parsed["access_token"], REDACTED)
			self.assertEqual(parsed["client_secret"], REDACTED)
			self.assertEqual(parsed["next"], f"https://api.example.invalid/v1/o?page=2&api_key={REDACTED}")
			self.assertEqual(parsed["id"], 7)
		self.assertEqual(redacted["traceback"], f"boom Authorization: Basic {REDACTED}")
		# the map only names fields: it is kept as it is
		self.assertEqual(redacted["map"], values["map"])

	def test_encoded_secret(self):
		from urllib.parse import quote

		secret = 'ab"c\\d/ef-é'
		connection = make_connection(
			"ES Redaction Encoded", auth_type="Header-based", api_key="X-Shop", secret=secret
		)
		values = {
			"response": "echo " + json.dumps({"echo": secret}),
			"traceback": "echo " + repr(secret),
			"url": "https://api.example.invalid/v1/x?q=" + quote(secret, safe=""),
			"document": json.dumps({"note": secret}),
		}
		redacted = redact_pull_log_values(values, connection.name)
		for field, value in redacted.items():
			self.assertIn(REDACTED, value, field)
			self.assertNotIn("ab", value.replace("api.example", ""), field)


class TestEspressoSyncPullLog(IntegrationTestCase):
	def test_new_pull_log_is_redacted_basic_auth(self):
		connection = make_connection(
			"ES Redaction Basic", auth_type="Basic", api_key="sync-user", secret=SECRET
		)
		headers = connection.get_request_headers()
		encoded = base64.b64encode(f"sync-user:{SECRET}".encode()).decode()
		self.assertEqual(headers["Authorization"], f"Basic {encoded}")

		connection.pull.sync_doctype = "ToDo"
		connection.pull.url = "https://sync-user:pw@api.example.invalid/v1/todos?token=abc&page=1"
		connection.pull.request = {"payload": None, "headers": headers}
		connection.pull.response = json.dumps({"echo": f"Basic {encoded}"})
		connection.pull.save()

		# the live headers used for the request are untouched
		self.assertEqual(headers["Authorization"], f"Basic {encoded}")

		log = latest_pull_log(connection.name)
		text = pull_log_text(log)
		self.assertNotIn(encoded, text)
		self.assertNotIn(SECRET, text)
		self.assertNotIn(":pw@", text)
		self.assertIn("page=1", log.url)
		request = log.request if isinstance(log.request, dict) else json.loads(log.request)
		self.assertEqual(request["headers"]["Authorization"], REDACTED)
		self.assertEqual(request["headers"]["Content-Type"], "application/json")

	def test_new_pull_log_is_redacted_header_auth(self):
		connection = make_connection(
			"ES Redaction Header", auth_type="Header-based", api_key="X-Shop-Header", secret=SECRET
		)
		connection.pull.sync_doctype = "ToDo"
		connection.pull.url = "https://api.example.invalid/v1/todos"
		connection.pull.request = json.dumps(
			{"payload": {"q": 1}, "headers": connection.get_request_headers()}, indent=4
		)
		connection.pull.save()

		log = latest_pull_log(connection.name)
		self.assertNotIn(SECRET, pull_log_text(log))
		self.assertEqual(json.loads(log.request)["headers"]["X-Shop-Header"], REDACTED)
		self.assertEqual(json.loads(log.request)["payload"], {"q": 1})

	def test_new_pull_log_redacts_object_and_document(self):
		connection = make_connection(
			"ES Redaction Object", auth_type="Basic", api_key="sync-user", secret=SECRET
		)
		encoded = base64.b64encode(f"sync-user:{SECRET}".encode()).decode()
		connection.pull.sync_doctype = "ToDo"
		connection.pull.object = json.dumps({"id": 1, "auth": f"Basic {encoded}", "echo": SECRET}, indent=4)
		connection.pull.document = json.dumps({"description": f"imported {SECRET}"})
		connection.pull.traceback = ValueError(f"failed with {SECRET}")
		connection.pull.save()

		log = latest_pull_log(connection.name)
		text = pull_log_text(log)
		self.assertNotIn(encoded, text)
		self.assertNotIn(SECRET, text)
		self.assertEqual(json.loads(log.object)["id"], 1)
		self.assertEqual(log.traceback, f"failed with {REDACTED}")


class TestPullLogRetention(IntegrationTestCase):
	def test_old_entries_are_cleared(self):
		from frappe.core.doctype.log_settings.log_settings import _supports_log_clearing

		self.assertEqual(
			frappe.get_hooks("default_log_clearing_doctypes", app_name="espresso_sync"),
			{"Espresso Sync Pull Log": [30]},
		)
		self.assertTrue(_supports_log_clearing("Espresso Sync Pull Log"))

		connection = make_connection("ES Retention Test")
		names = []
		for age in (40, 1):
			connection.pull.sync_doctype = "ToDo"
			connection.pull.sync_status = "Success"
			connection.pull.save()
			name = frappe.get_all(
				"Espresso Sync Pull Log",
				filters={"sync_connection": connection.name},
				order_by="creation desc",
				pluck="name",
				limit=1,
			)[0]
			frappe.db.set_value(
				"Espresso Sync Pull Log",
				name,
				"creation",
				frappe.utils.add_days(frappe.utils.now_datetime(), -age),
				update_modified=False,
			)
			names.append(name)

		EspressoSyncPullLog.clear_old_logs(days=30)
		self.assertFalse(frappe.db.exists("Espresso Sync Pull Log", names[0]))
		self.assertTrue(frappe.db.exists("Espresso Sync Pull Log", names[1]))
