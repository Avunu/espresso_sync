# Copyright (c) 2023, Avunu LLC and Contributors
# See license.txt

import base64
import json

import frappe

try:
	from frappe.tests import IntegrationTestCase
except ImportError:  # frappe < 16
	from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from espresso_sync.espresso_sync.doctype.espresso_sync_connection.test_espresso_sync_connection import (
	make_connection,
)
from espresso_sync.patches import redact_pull_log_secrets
from espresso_sync.redaction import REDACTED, redact_request, redact_text, redact_url

SECRET = "hunter2-secret-value"


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
	return " ".join(str(doc.get(f) or "") for f in ("url", "request", "response", "traceback"))


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


class TestEspressoSyncPullLog(IntegrationTestCase):
	def test_new_pull_log_is_redacted_basic_auth(self):
		connection = make_connection("ES Redaction Basic", auth_type="Basic", api_key="sync-user", secret=SECRET)
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

	def test_patch_scrubs_existing_rows(self):
		connection = make_connection("ES Redaction Patch", auth_type="Basic", api_key="sync-user", secret=SECRET)
		encoded = base64.b64encode(f"sync-user:{SECRET}".encode()).decode()
		header_conn = make_connection(
			"ES Redaction Patch Header", auth_type="Header-based", api_key="X-Shop-Header", secret=SECRET
		)

		def seed(connection_name, values):
			log = frappe.get_doc(
				{"doctype": "Espresso Sync Pull Log", "sync_connection": connection_name, "sync_doctype": "ToDo"}
			).insert(ignore_permissions=True)
			# write the plaintext the way rows were stored before redaction existed
			frappe.db.set_value("Espresso Sync Pull Log", log.name, values, update_modified=False)
			return log.name, frappe.db.get_value("Espresso Sync Pull Log", log.name, "modified")

		json_row, json_modified = seed(
			connection.name,
			{
				"url": "https://sync-user:pw@api.example.invalid/v1/todos?api_key=abc",
				"request": json.dumps(
					{"payload": None, "headers": {"Authorization": f"Basic {encoded}", "Content-Type": "application/json"}},
					indent=4,
				),
				"response": f"you sent {SECRET}",
				"traceback": f"401 for Authorization: Basic {encoded}",
			},
		)
		# Request is a JSON column; free text such as a traceback can hold a repr of the headers
		repr_row, _ = seed(
			header_conn.name,
			{"traceback": str({"payload": None, "headers": {"X-Shop-Header": "short", "Content-Type": "application/json"}})},
		)
		clean_row, clean_modified = seed(
			connection.name,
			{"url": "https://api.example.invalid/v1/todos", "request": json.dumps({"payload": None, "headers": {}})},
		)
		clean_before = frappe.db.get_value("Espresso Sync Pull Log", clean_row, ["url", "request"], as_dict=True)

		redact_pull_log_secrets.execute()

		row = frappe.get_doc("Espresso Sync Pull Log", json_row)
		text = pull_log_text(row)
		self.assertNotIn(encoded, text)
		self.assertNotIn(SECRET, text)
		self.assertNotIn(":pw@", text)
		self.assertNotIn("api_key=abc", text)
		self.assertEqual(json.loads(row.request)["headers"]["Authorization"], REDACTED)
		self.assertEqual(json.loads(row.request)["headers"]["Content-Type"], "application/json")
		self.assertEqual(row.modified, json_modified)

		self.assertEqual(
			frappe.db.get_value("Espresso Sync Pull Log", repr_row, "traceback"),
			str({"payload": None, "headers": {"X-Shop-Header": REDACTED, "Content-Type": "application/json"}}),
		)

		self.assertEqual(
			frappe.db.get_value("Espresso Sync Pull Log", clean_row, ["url", "request"], as_dict=True), clean_before
		)
		self.assertEqual(frappe.db.get_value("Espresso Sync Pull Log", clean_row, "modified"), clean_modified)
