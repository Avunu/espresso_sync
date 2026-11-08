# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

import json
from pathlib import Path

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field
from frappe.tests import IntegrationTestCase
from jsonschema import Draft202012Validator

from espresso_sync.schema.doctype_schema import doctype_json_schema, validate_doctype_payload
from espresso_sync.sync import ensure_sync_fields

GOLDEN = Path(__file__).parent / "fixtures" / "contact_insert.json"
# the part of Contact's schema the golden file holds: the DocType, a Data field, a Link, a
# Check, a Select, a read-only field, and the three child tables (Dynamic Link among them)
GOLDEN_FIELDS = (
	"doctype",
	"first_name",
	"user",
	"status",
	"unsubscribed",
	"full_name",
	"email_ids",
	"phone_nos",
	"links",
)
CUSTOM_FIELD = "es_schema_test_rating"


def golden_view(schema: dict) -> dict:
	return {
		**{key: value for key, value in schema.items() if key != "properties"},
		"properties": {fieldname: schema["properties"][fieldname] for fieldname in GOLDEN_FIELDS},
	}


def codes(diagnostics) -> set[tuple[str, str, str]]:
	return {(d["path"], d["code"], d["severity"]) for d in diagnostics}


class TestDocTypeSchema(IntegrationTestCase):
	def test_contact_golden(self):
		schema = doctype_json_schema("Contact", "insert")
		Draft202012Validator.check_schema(schema)
		self.assertEqual(golden_view(schema), json.loads(GOLDEN.read_text()))

	def test_the_contract_shape(self):
		schema = doctype_json_schema("Contact", "read")
		self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
		self.assertEqual(schema["x-frappe"], {"doctype": "Contact", "mode": "read", "istable": False})
		self.assertFalse(schema["additionalProperties"])
		for fieldname, field in schema["properties"].items():
			with self.subTest(fieldname=fieldname):
				self.assertEqual(
					set(field["x-frappe"]),
					{"fieldtype", "options", "link", "dynamic_link", "required", "read_only", "custom"},
				)
		links = schema["properties"]["links"]
		self.assertEqual(links["x-frappe"]["fieldtype"], "Table")
		self.assertEqual(links["x-frappe"]["options"], "Dynamic Link")
		self.assertIsNone(links["x-frappe"]["link"])
		row = links["items"]
		self.assertNotIn("$schema", row)
		self.assertEqual(row["x-frappe"], {"doctype": "Dynamic Link", "mode": "read", "istable": True})
		self.assertEqual(row["properties"]["link_name"]["x-frappe"]["dynamic_link"], "link_doctype")
		self.assertEqual(row["properties"]["link_doctype"]["x-frappe"]["link"], "DocType")
		# as read, a document has its standard fields, and a row its parent's
		for fieldname in ("name", "owner", "creation", "modified", "modified_by", "docstatus", "idx"):
			self.assertIn(fieldname, schema["properties"])
		self.assertIn("parenttype", row["properties"])
		self.assertEqual(schema["properties"]["modified"]["format"], "date-time")
		# nothing is required of a document read, or of an update
		self.assertEqual(schema["required"], [])
		self.assertEqual(doctype_json_schema("Contact", "update")["required"], [])
		self.assertIsNone(
			doctype_json_schema("Contact", "update")["properties"]["links"]["items"]["properties"][
				"link_name"
			]["x-frappe"]["required"]
		)
		self.assertRaises(frappe.ValidationError, doctype_json_schema, "Contact", "delete")

	def test_a_document_as_read_validates(self):
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "Schema",
				"last_name": "Reader",
				"email_ids": [{"email_id": "schema.reader@example.com", "is_primary": 1}],
			}
		).insert(ignore_permissions=True)
		# the shape Frappe gives a document in: doctype, and __unsaved on new rows, included
		document = contact.as_dict(no_default_fields=False)
		document["email_ids"][0]["__unsaved"] = 1
		payload = json.loads(frappe.as_json(document))
		self.assertEqual(payload["doctype"], "Contact")
		self.assertEqual(payload["email_ids"][0]["doctype"], "Contact Email")
		diagnostics = validate_doctype_payload("Contact", payload, "read")
		self.assertEqual([d for d in diagnostics if d["severity"] != "info"], [])
		schema = doctype_json_schema("Contact", "read")
		self.assertEqual(schema["properties"]["doctype"]["const"], "Contact")
		self.assertEqual(
			schema["properties"]["email_ids"]["items"]["properties"]["doctype"]["const"], "Contact Email"
		)
		# another DocType's document is not this one's
		payload["email_ids"][0]["doctype"] = "Contact Phone"
		self.assertIn(
			("/email_ids/0/doctype", "schema-const", "error"),
			codes(validate_doctype_payload("Contact", payload, "read")),
		)

	def test_a_custom_field_appears(self):
		create_custom_field(
			"Contact",
			{"fieldname": CUSTOM_FIELD, "fieldtype": "Int", "label": "ES Rating", "insert_after": "status"},
		)
		self.addCleanup(frappe.delete_doc, "Custom Field", f"Contact-{CUSTOM_FIELD}", force=True)
		field = doctype_json_schema("Contact", "insert")["properties"][CUSTOM_FIELD]
		self.assertEqual(field["type"], "integer")
		self.assertEqual(field["title"], "ES Rating")
		self.assertTrue(field["x-frappe"]["custom"])

	def test_layout_virtual_and_sync_fields_are_left_out(self):
		ensure_sync_fields("ToDo")
		properties = doctype_json_schema("ToDo", "insert")["properties"]
		for fieldname in ("espresso_sync_ids", "exclude_from_sync", "espresso_sync_tab"):
			self.assertNotIn(fieldname, properties)
		meta = frappe.get_meta("ToDo")
		layout = [df.fieldname for df in meta.fields if df.fieldtype in ("Section Break", "Column Break")]
		self.assertTrue(layout)
		self.assertFalse(set(layout) & set(properties))
		self.assertEqual(properties["date"]["format"], "date")
		self.assertEqual(properties["description"]["x-frappe"]["required"], "hard")
		self.assertEqual(doctype_json_schema("ToDo", "insert")["required"], ["description"])

	def test_hard_and_server_requiredness(self):
		schema = doctype_json_schema("Reminder", "insert")
		required = {name: field["x-frappe"]["required"] for name, field in schema["properties"].items()}
		self.assertEqual(required["description"], "hard")
		# defaults: the session user, and now
		self.assertEqual(required["user"], "server")
		self.assertEqual(required["remind_at"], "server")
		self.assertEqual(schema["required"], ["description"])


class TestDocTypePayloads(IntegrationTestCase):
	def test_coercions_are_warnings(self):
		diagnostics = validate_doctype_payload(
			"Contact",
			{
				"first_name": "Ada",
				"unsubscribed": True,
				"is_primary_contact": "1",
				"sync_with_google_contacts": 2,
				"email_ids": [{"email_id": "ada@example.com", "is_primary": False}],
				"status": "",
				"last_name": None,
				"nickname": "x",
			},
		)
		self.assertEqual(
			codes(diagnostics),
			{
				("/unsubscribed", "check-boolean", "info"),
				("/email_ids/0/is_primary", "check-boolean", "info"),
				("/is_primary_contact", "numeric-string", "warning"),
				("/sync_with_google_contacts", "check-number", "warning"),
				("", "unknown-field", "warning"),
			},
		)

	def test_what_frappe_refuses_is_an_error(self):
		diagnostics = validate_doctype_payload(
			"ToDo",
			{
				"description": None,
				"status": "Bogus",
				"date": "not a date",
				"priority": "Medium",
				"color": "x" * 200,
				"sender": "not an email",
			},
		)
		self.assertEqual(
			codes(diagnostics),
			{
				("/description", "required", "error"),
				("/status", "schema-enum", "error"),
				("/date", "schema-format", "error"),
				("/color", "schema-maxLength", "error"),
				("/sender", "schema-format", "error"),
			},
		)
		missing = validate_doctype_payload("Contact", {"email_ids": [{"is_primary": 1}]})
		self.assertEqual(codes(missing), {("/email_ids/0/email_id", "required", "error")})
		self.assertEqual(validate_doctype_payload("ToDo", {"priority": "Low"}, "update"), [])
		# get_doc's shape: the DocType named in the payload
		self.assertEqual(validate_doctype_payload("ToDo", {"doctype": "ToDo", "description": "x"}), [])

	def test_an_empty_mandatory_value_is_an_error(self):
		required = {("/description", "required", "error")}
		for value in (None, "", "  ", "<p><br></p>"):
			with self.subTest(value=value):
				self.assertEqual(codes(validate_doctype_payload("ToDo", {"description": value})), required)
				# an update fills nothing in: an empty mandatory field is refused on save
				self.assertEqual(
					codes(validate_doctype_payload("ToDo", {"description": value}, "update")), required
				)
		self.assertEqual(validate_doctype_payload("ToDo", {"description": '<p><img src="a.png"></p>'}), [])
		self.assertEqual(
			codes(validate_doctype_payload("User Group", {"name": "ES Group", "user_group_members": []})),
			{("/user_group_members", "required", "error")},
		)
		self.assertEqual(
			codes(validate_doctype_payload("Contact", {"email_ids": [{"email_id": ""}]})),
			{("/email_ids/0/email_id", "required", "error")},
		)
		# a field left out of an update is left as it is
		self.assertEqual(validate_doctype_payload("ToDo", {}, "update"), [])
		# a saved document gets no defaults: a mandatory field with one is refused empty too
		self.assertEqual(
			codes(validate_doctype_payload("Reminder", {"remind_at": None}, "update")),
			{("/remind_at", "required", "error")},
		)

	def test_numbers(self):
		create_custom_field(
			"ToDo",
			{
				"fieldname": "es_schema_count",
				"fieldtype": "Int",
				"label": "ES Count",
				"insert_after": "status",
			},
		)
		self.addCleanup(frappe.delete_doc, "Custom Field", "ToDo-es_schema_count", force=True)
		diagnostics = validate_doctype_payload("ToDo", {"es_schema_count": "12"}, "update")
		self.assertEqual(codes(diagnostics), {("/es_schema_count", "numeric-string", "warning")})
		diagnostics = validate_doctype_payload("ToDo", {"es_schema_count": 1.5}, "update")
		self.assertEqual(codes(diagnostics), {("/es_schema_count", "numeric-string", "warning")})
		diagnostics = validate_doctype_payload("ToDo", {"es_schema_count": "twelve"}, "update")
		self.assertEqual(codes(diagnostics), {("/es_schema_count", "schema-type", "error")})

	def test_server_filled_fields_are_warnings(self):
		diagnostics = validate_doctype_payload("Reminder", {"description": "call"})
		self.assertEqual(
			codes(diagnostics),
			{("/user", "server-filled", "warning"), ("/remind_at", "server-filled", "warning")},
		)
