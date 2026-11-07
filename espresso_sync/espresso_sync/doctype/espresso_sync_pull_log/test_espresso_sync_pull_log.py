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
from espresso_sync.patches import redact_pull_log_secrets
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

	def test_patch_scrubs_existing_rows(self):
		connection = make_connection(
			"ES Redaction Patch", auth_type="Basic", api_key="sync-user", secret=SECRET
		)
		encoded = base64.b64encode(f"sync-user:{SECRET}".encode()).decode()
		header_conn = make_connection(
			"ES Redaction Patch Header", auth_type="Header-based", api_key="X-Shop-Header", secret=SECRET
		)

		def seed(connection_name, values):
			log = frappe.get_doc(
				{
					"doctype": "Espresso Sync Pull Log",
					"sync_connection": connection_name,
					"sync_doctype": "ToDo",
				}
			).insert(ignore_permissions=True)
			# write the plaintext the way rows were stored before redaction existed
			frappe.db.set_value("Espresso Sync Pull Log", log.name, values, update_modified=False)
			return log.name, frappe.db.get_value("Espresso Sync Pull Log", log.name, "modified")

		json_row, json_modified = seed(
			connection.name,
			{
				"url": "https://sync-user:pw@api.example.invalid/v1/todos?api_key=abc",
				"request": json.dumps(
					{
						"payload": None,
						"headers": {"Authorization": f"Basic {encoded}", "Content-Type": "application/json"},
					},
					indent=4,
				),
				"response": f"you sent {SECRET}",
				"traceback": f"401 for Authorization: Basic {encoded}",
			},
		)
		# Request is a JSON column; free text such as a traceback can hold a repr of the headers
		repr_row, _ = seed(
			header_conn.name,
			{
				"traceback": str(
					{
						"payload": None,
						"headers": {"X-Shop-Header": "short", "Content-Type": "application/json"},
					}
				)
			},
		)
		clean_row, clean_modified = seed(
			connection.name,
			{
				"url": "https://api.example.invalid/v1/todos",
				"request": json.dumps({"payload": None, "headers": {}}),
			},
		)
		object_row, _ = seed(
			connection.name,
			{
				"object": json.dumps(
					{"id": 1, "echo": f"Basic {encoded}", "access_token": "tok-AAAA"}, indent=4
				),
				"response": json.dumps(
					{"next": "https://api.example.invalid/v1/todos?page=2&api_key=KEYKEY"}
				),
				"document": json.dumps({"description": SECRET}),
			},
		)
		clean_before = frappe.db.get_value(
			"Espresso Sync Pull Log", clean_row, ["url", "request"], as_dict=True
		)
		# a failed Pull Log save used to log the whole unredacted row
		error_log = frappe.log_error(
			"Error saving pull log",
			"error: boom\npull_log: "
			+ str(
				{
					"sync_connection": connection.name,
					"request": {"payload": None, "headers": {"Authorization": f"Basic {encoded}"}},
					"response": f"you sent {SECRET}",
				}
			),
		)

		redact_pull_log_secrets.execute()

		row = get_pull_log(json_row)
		text = pull_log_text(row)
		self.assertNotIn(encoded, text)
		self.assertNotIn(SECRET, text)
		self.assertNotIn(":pw@", text)
		self.assertNotIn("api_key=abc", text)
		self.assertEqual(json.loads(row.request or "")["headers"]["Authorization"], REDACTED)
		self.assertEqual(json.loads(row.request or "")["headers"]["Content-Type"], "application/json")
		self.assertEqual(row.modified, json_modified)

		self.assertEqual(
			frappe.db.get_value("Espresso Sync Pull Log", repr_row, "traceback"),
			str(
				{"payload": None, "headers": {"X-Shop-Header": REDACTED, "Content-Type": "application/json"}}
			),
		)

		row = get_pull_log(object_row)
		text = pull_log_text(row)
		for secret in (encoded, SECRET, "tok-AAAA", "KEYKEY"):
			self.assertNotIn(secret, text)
		self.assertEqual(json.loads(row.object or "")["id"], 1)

		error = frappe.db.get_value("Error Log", error_log.name, "error")
		self.assertNotIn(encoded, error)
		self.assertNotIn(SECRET, error)
		self.assertIn(f"'Authorization': 'Basic {REDACTED}'", error)

		self.assertEqual(
			frappe.db.get_value("Espresso Sync Pull Log", clean_row, ["url", "request"], as_dict=True),
			clean_before,
		)
		self.assertEqual(frappe.db.get_value("Espresso Sync Pull Log", clean_row, "modified"), clean_modified)


class TestDeleteBatchPatch(IntegrationTestCase):
	def test_the_doctype_and_its_table_are_removed(self):
		from espresso_sync.patches import delete_espresso_sync_batch

		frappe.set_user("Administrator")
		doctype = delete_espresso_sync_batch.DOCTYPE
		if not frappe.db.exists("DocType", doctype):
			# what a site installed before the removal still has
			frappe.get_doc(
				{
					"doctype": "DocType",
					"name": doctype,
					"module": "Espresso Sync",
					"custom": 1,
					"fields": [
						{
							"fieldname": "sync_connection",
							"fieldtype": "Link",
							"options": "Espresso Sync Connection",
						},
						{"fieldname": "objects_processed", "fieldtype": "Int"},
					],
					"permissions": [{"role": "System Manager", "read": 1}],
				}
			).insert()
			frappe.db.set_value("DocType", doctype, "custom", 0)
		self.assertTrue(frappe.db.table_exists(doctype, cached=False))

		# as bench migrate runs it
		in_migrate = frappe.flags.in_migrate
		frappe.flags.in_migrate = True
		try:
			delete_espresso_sync_batch.execute()
			self.assertFalse(frappe.db.exists("DocType", doctype))
			self.assertFalse(frappe.db.table_exists(doctype, cached=False))
			# and again: a patch may run on a site that never had it
			delete_espresso_sync_batch.execute()
		finally:
			frappe.flags.in_migrate = in_migrate
