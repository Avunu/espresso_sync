# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

import inspect
import json
from pathlib import Path
from typing import cast
from unittest.mock import patch

import frappe
import responses
from frappe.share import add as share_doc
from frappe.tests import IntegrationTestCase

from espresso_sync.api import schema as api
from espresso_sync.espresso_sync.doctype.espresso_sync_api_spec.espresso_sync_api_spec import (
	EspressoSyncAPISpec,
)
from espresso_sync.tests.egress import public_dns

FIXTURES = Path(__file__).parent / "fixtures" / "openapi"
WEBSITE_USER = "es-schema-website@example.com"
DESK_USER = "es-schema-desk@example.com"
MANAGER_USER = "es-schema-manager@example.com"
DESK_ROLE = "Espresso Sync Schema Test Desk Role"
CONNECTION = "ES Schema API Test"
SPEC_URL = "https://api.example.invalid/openapi.yaml"


def make_user(email, roles=()):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"roles": [{"role": role} for role in roles],
			}
		).insert(ignore_permissions=True)
	return email


def fixture_text(name: str) -> str:
	return (FIXTURES / name).read_text()


def as_json(name: str) -> str:
	return json.dumps(api.openapi.load_spec_text(fixture_text(name)))


class TestSchemaEndpoints(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		if not frappe.db.exists("Role", DESK_ROLE):
			frappe.get_doc({"doctype": "Role", "role_name": DESK_ROLE, "desk_access": 1}).insert(
				ignore_permissions=True
			)
		make_user(WEBSITE_USER)
		make_user(DESK_USER, [DESK_ROLE])
		make_user(MANAGER_USER, ["System Manager"])
		if not frappe.db.exists("Espresso Sync Connection", CONNECTION):
			frappe.get_doc(
				{
					"doctype": "Espresso Sync Connection",
					"connection_name": CONNECTION,
					"auth_type": "Header-based",
					"api_key": "X-Api-Key",
					"api_secret": "schema-api-secret",
					"server_url": "https://api.example.invalid/v1",
					"sync_frequency": "Manual",
				}
			).insert(ignore_permissions=True)

	def setUp(self):
		super().setUp()
		self.enterContext(public_dns())
		frappe.set_user("Administrator")
		for name in (f"{CONNECTION} - Payments", "Other", "ES Standalone Shop"):
			frappe.delete_doc(api.SPEC, name, force=True, ignore_missing=True)
		self.spec = api.save_spec(as_json("composition.yaml"), "Payments", connection=CONNECTION)["name"]
		share_doc(api.SPEC, self.spec, DESK_USER, read=1, write=1, notify=0)

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def endpoints(self):
		return {
			"fetch_spec_source": lambda: api.fetch_spec_source(SPEC_URL),
			"save_spec": lambda: api.save_spec(as_json("oas31.yaml"), "Other"),
			"list_operations": lambda: api.list_operations(self.spec),
			"get_operation_schema": lambda: api.get_operation_schema(self.spec, "post", "/payments"),
			"list_doctypes": api.list_doctypes,
			"get_doctype_schema": lambda: api.get_doctype_schema("Contact"),
			"validate_payload": lambda: api.validate_payload("{}", doctype="Contact"),
		}

	def test_every_endpoint_is_covered(self):
		whitelisted = {
			name for name, fn in inspect.getmembers(api, inspect.isfunction) if fn in frappe.whitelisted
		}
		self.assertEqual(whitelisted, set(self.endpoints()))

	def test_only_a_system_manager(self):
		with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
			rsps.add(responses.GET, SPEC_URL, body=fixture_text("oas31.yaml"))
			for user in (WEBSITE_USER, DESK_USER):
				for name, call in self.endpoints().items():
					frappe.set_user(user)
					with self.subTest(endpoint=name, user=user), self.assertRaises(frappe.PermissionError):
						call()
			self.assertEqual(len(rsps.calls), 0)
			frappe.set_user(MANAGER_USER)
			for name, call in self.endpoints().items():
				with self.subTest(endpoint=name, user=MANAGER_USER):
					call()

	def test_save_spec(self):
		doc = cast(EspressoSyncAPISpec, frappe.get_doc(api.SPEC, self.spec))
		self.assertEqual(doc.name, f"{CONNECTION} - Payments")
		self.assertEqual(json.loads(doc.operations or "[]")[0]["operation_id"], "createPayment")
		self.assertEqual(len(doc.spec_hash or ""), 64)
		self.assertEqual(doc.original_version, "3.1.0")
		self.assertTrue(frappe.get_meta(api.SPEC).track_changes)
		# saving it again changes nothing; a changed spec gets a new hash
		again = api.save_spec(as_json("composition.yaml"), "Payments", name=self.spec)
		self.assertFalse(again["changed"])
		spec = api.openapi.load_spec_text(fixture_text("composition.yaml"))
		spec["info"]["version"] = "2"
		changed = api.save_spec(
			json.dumps(spec), "Payments", name=self.spec, source_format="Swagger 2.0", original_version="2.0"
		)
		self.assertTrue(changed["changed"])
		self.assertEqual(changed["name"], self.spec)
		doc.reload()
		self.assertEqual((doc.source_format, doc.original_version), ("Swagger 2.0", "2.0"))
		# the hints are offered, the Connection is left as it was
		self.assertEqual(
			{hint["scheme"] for hint in changed["auth_hints"]}, {"apiKey", "basic", "bearer", "oauth"}
		)
		self.assertEqual(
			frappe.db.get_value("Espresso Sync Connection", CONNECTION, "auth_type"), "Header-based"
		)
		self.assertEqual(frappe.db.get_value("Espresso Sync Connection", CONNECTION, "api_key"), "X-Api-Key")

	def test_save_spec_refuses_anything_but_bundled_31(self):
		for text in (fixture_text("oas30.yaml"), fixture_text("sw2.yaml"), "not: [a spec"):
			with self.subTest(text=text[:20]), self.assertRaises(frappe.ValidationError):
				api.save_spec(text, "Refused")
		spec = api.openapi.load_spec_text(fixture_text("oas31.yaml"))
		spec["components"]["schemas"]["Order"] = {"$ref": "file:///etc/passwd"}
		with self.assertRaises(frappe.ValidationError):
			api.save_spec(json.dumps(spec), "Refused")
		# the desk form checks the same
		doc = cast(EspressoSyncAPISpec, frappe.get_doc(api.SPEC, self.spec))
		doc.spec_json = fixture_text("oas30.yaml")
		self.assertRaises(frappe.ValidationError, doc.save)

	def test_operations_and_schemas(self):
		operations = api.list_operations(self.spec)
		self.assertEqual([(op["method"], op["path"]) for op in operations], [("POST", "/payments")])
		result = api.get_operation_schema(self.spec, "post", "/payments", "requestBody")
		self.assertEqual(result["media_type"], "application/json")
		self.assertIsNone(result["status"])
		self.assertEqual(len(result["schema"]["allOf"]), 2)
		self.assertEqual(api.get_operation_schema(self.spec, "post", "/payments")["status"], "201")
		with self.assertRaises(frappe.ValidationError):
			api.get_operation_schema(self.spec, "get", "/payments")

	def test_validate_payload(self):
		diagnostics = api.validate_payload(
			json.dumps({"amount": "x", "method": {"kind": "card", "last4": "1234"}}),
			spec=self.spec,
			method="post",
			path="/payments",
		)
		self.assertEqual([(d["path"], d["code"]) for d in diagnostics], [("/amount", "schema-type")])
		diagnostics = api.validate_payload({"description": None}, doctype="ToDo")
		self.assertEqual([(d["path"], d["code"]) for d in diagnostics], [("/description", "required")])
		self.assertRaises(frappe.ValidationError, api.validate_payload, "{", doctype="ToDo")
		self.assertRaises(frappe.ValidationError, api.validate_payload, "{}", spec=self.spec)

	def test_get_doctype_schema_checks_read_permission(self):
		frappe.set_user(MANAGER_USER)
		self.assertEqual(api.get_doctype_schema("Contact", "update")["x-frappe"]["mode"], "update")
		with (
			patch.object(frappe, "has_permission", return_value=False),
			self.assertRaises(frappe.PermissionError),
		):
			api.get_doctype_schema("Contact")
		with (
			patch.object(frappe, "has_permission", return_value=False),
			self.assertRaises(frappe.PermissionError),
		):
			api.validate_payload("{}", doctype="Contact")
		self.assertRaises(frappe.ValidationError, api.get_doctype_schema, "Contact Email")
		self.assertRaises(frappe.DoesNotExistError, api.get_doctype_schema, "No Such DocType")
		self.assertRaises(frappe.ValidationError, api.get_doctype_schema, "Contact", "delete")

	def test_list_doctypes(self):
		frappe.set_user(MANAGER_USER)
		doctypes = api.list_doctypes()
		self.assertIn("Contact", doctypes)
		self.assertEqual(doctypes, sorted(doctypes, key=str.casefold))
		# a child table, a Single, and a DocType the user can't read are not offered
		self.assertNotIn("Contact Email", doctypes)
		self.assertNotIn("System Settings", doctypes)
		with patch.object(frappe.get_user(), "get_can_read", return_value=["ToDo", "Contact Email"]):
			self.assertEqual(api.list_doctypes(), ["ToDo"])

	def test_fetch_spec_source(self):
		with responses.RequestsMock() as rsps:
			rsps.add(
				responses.GET, SPEC_URL, body=fixture_text("oas31.yaml"), content_type="application/yaml"
			)
			rsps.add(responses.GET, "https://elsewhere.example.invalid/spec.json", json={"openapi": "3.1.0"})
			fetched = api.fetch_spec_source(SPEC_URL)
			self.assertEqual(fetched["text"], fixture_text("oas31.yaml"))
			self.assertEqual(fetched["content_type"], "application/yaml")
			self.assertNotIn("X-Api-Key", rsps.calls[0].request.headers)
			# with a Connection, its credentials go to its Allowed Host only
			api.fetch_spec_source(SPEC_URL, connection=CONNECTION)
			self.assertEqual(rsps.calls[1].request.headers.get("X-Api-Key"), "schema-api-secret")
			api.fetch_spec_source("https://elsewhere.example.invalid/spec.json", connection=CONNECTION)
			self.assertNotIn("X-Api-Key", rsps.calls[2].request.headers)

	def test_fetch_spec_source_refusals(self):
		with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
			rsps.add(responses.GET, "http://169.254.169.254/latest/meta-data/", body="secret")
			rsps.add(responses.GET, f"{SPEC_URL}?missing", status=404)
			for url in ("file:///etc/passwd", "http://169.254.169.254/latest/meta-data/"):
				with self.subTest(url=url), self.assertRaises(frappe.ValidationError):
					api.fetch_spec_source(url)
			self.assertEqual(len(rsps.calls), 0)
			with self.assertRaises(frappe.ValidationError):
				api.fetch_spec_source(f"{SPEC_URL}?missing")
		with (
			patch.object(api, "safe_request", side_effect=RuntimeError("boom")),
			self.assertRaises(frappe.ValidationError),
		):
			api.fetch_spec_source(SPEC_URL)
		with responses.RequestsMock() as rsps:
			rsps.add(responses.GET, SPEC_URL, body=b"x" * 64)
			rsps.add(responses.GET, SPEC_URL, body=b"x" * 64)
			# the fetch has its own cap, above a stored spec's: a published spec is pretty-printed
			self.assertGreater(api.MAX_SOURCE_BYTES, api.openapi.MAX_SPEC_BYTES)
			with patch.object(api.openapi, "MAX_SPEC_BYTES", 16):
				self.assertEqual(len(api.fetch_spec_source(SPEC_URL)["text"]), 64)
			with patch.object(api, "MAX_SOURCE_BYTES", 16), self.assertRaises(frappe.ValidationError):
				api.fetch_spec_source(SPEC_URL)

	def test_a_spec_without_a_connection_is_named_by_its_title(self):
		name = api.save_spec(as_json("oas31.yaml"), "ES Standalone Shop")["name"]
		self.assertEqual(name, "ES Standalone Shop")
		self.assertIsNone(frappe.db.get_value(api.SPEC, name, "connection"))
