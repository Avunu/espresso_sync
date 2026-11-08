# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

from decimal import Decimal
from unittest.mock import patch

import frappe
import frappe.apps
from frappe.tests import IntegrationTestCase

from espresso_sync import map_machine
from espresso_sync.dynamic_tags import get_linked_doctype, id_tag
from espresso_sync.map_machine import evaluate_jsonata, extract_object, tamp_dynamic_parameter


class TestEvaluateJsonata(IntegrationTestCase):
	def test_a_bad_expression_gives_none(self):
		self.assertIsNone(evaluate_jsonata("lines[", {"lines": []}))

	def test_extract_object(self):
		self.assertEqual(
			extract_object(
				{"title": "subject", "upper": "$uppercase(subject)", "count": 3, "nested": {"id": "id"}},
				{"subject": "Espresso", "id": 7},
			),
			{"title": "Espresso", "upper": "ESPRESSO", "count": 3, "nested": {"id": 7}},
		)

	def test_undefined_keys_are_left_out(self):
		self.assertEqual(
			extract_object(
				{"title": "subject", "missing": "no_such_field", "empty": "nothing", "broken": "lines["},
				{"subject": "Espresso", "nothing": None},
			),
			# null is a value; undefined and a failed expression are not
			{"title": "Espresso", "empty": None},
		)
		self.assertIsNone(evaluate_jsonata("no_such_field", {}))
		self.assertIs(
			evaluate_jsonata("no_such_field", {}, default=map_machine.UNDEFINED), map_machine.UNDEFINED
		)
		self.assertEqual(evaluate_jsonata("[a, null]", {"a": 1}), [1, None])

	def test_match_reads_whole_numbers_as_integers(self):
		object_map = {
			"label": {"match": {"match-on": "$.qty", "cases": {"3": "three", "2.5": "two and a half"}}}
		}
		self.assertEqual(extract_object(object_map, {"qty": Decimal("3")}), {"label": "three"})
		self.assertEqual(extract_object(object_map, {"qty": 3}), {"label": "three"})
		self.assertEqual(extract_object(object_map, {"qty": Decimal("2.5")}), {"label": "two and a half"})
		self.assertEqual(extract_object(object_map, {"qty": 4}), {"label": None})


class TestDynamicParameter(IntegrationTestCase):
	def test_id_tag_reads_each_document(self):
		todos = [
			frappe.get_doc({"doctype": "ToDo", "description": f"tamp {n}"}).insert(ignore_permissions=True)
			for n in (1, 2)
		]
		shot = frappe._dict(dt="ToDo")
		connection = frappe._dict(name="ES Tamp Test")
		with patch(
			"espresso_sync.map_machine.extract_dynamic_tag",
			side_effect=lambda tag, object, sync_connection, doc: f"ext-{doc['description']}",
		) as extract:
			urls = tamp_dynamic_parameter(
				"https://api.example.invalid/{id:description}", shot, connection, [t.name for t in todos]
			)
		self.assertEqual(
			urls, ['https://api.example.invalid/"ext-tamp 1"', 'https://api.example.invalid/"ext-tamp 2"']
		)
		self.assertEqual([c.args[3]["name"] for c in extract.call_args_list], [t.name for t in todos])

	def test_no_documents_gives_the_url_once(self):
		shot = frappe._dict(dt="ToDo")
		connection = frappe._dict(name="ES Tamp Test")
		for doc_names in (None, []):
			with self.subTest(doc_names=doc_names):
				self.assertEqual(
					tamp_dynamic_parameter("https://api.example.invalid/todos", shot, connection, doc_names),
					["https://api.example.invalid/todos"],
				)


class TestAppsScreen(IntegrationTestCase):
	def test_hidden_from_the_apps_screen(self):
		# the entry is there for the About dialog's logo
		self.assertTrue(frappe.get_hooks("add_to_apps_screen", app_name="espresso_sync"))
		frappe.set_user("Administrator")
		self.assertIn("System Manager", frappe.get_roles())
		self.assertNotIn("espresso_sync", [app["name"] for app in frappe.apps.get_apps()])


class TestIdTag(IntegrationTestCase):
	def test_the_linked_doctype_narrows_the_lookup(self):
		todo = frappe._dict(
			doctype="ToDo", name="T1", reference_type="Note", reference_name="N1", role="System Manager"
		)
		self.assertEqual(get_linked_doctype(todo, "name"), "ToDo")
		self.assertEqual(get_linked_doctype(todo, "role"), "Role")
		self.assertEqual(get_linked_doctype(todo, "reference_name"), "Note")
		self.assertIsNone(get_linked_doctype(todo, "description"))
		self.assertIsNone(get_linked_doctype(todo, "no_such_field"))
		self.assertIsNone(get_linked_doctype(frappe._dict(name="x"), "name"))

		connection = frappe._dict(name="ES Id Tag Test")
		with patch.object(frappe.db, "get_value", return_value="ext-1") as get_value:
			self.assertEqual(id_tag("reference_name", None, connection, todo), "ext-1")
		self.assertEqual(
			get_value.call_args.kwargs["filters"],
			{"sync_connection": "ES Id Tag Test", "parent": "N1", "parenttype": "Note"},
		)
