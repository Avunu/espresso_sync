# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

import datetime
from decimal import Decimal
from unittest.mock import patch

import frappe
import frappe.apps
from frappe.tests import IntegrationTestCase

from espresso_sync.map_machine import evaluate_jsonata, extract_object, tamp_dynamic_parameter


class TestEvaluateJsonata(IntegrationTestCase):
	def test_frappe_values_are_read_as_json(self):
		data = frappe._dict(
			when=datetime.datetime(2026, 1, 15, 9, 30),
			day=datetime.date(2026, 1, 15),
			amount=Decimal("12.50"),
			lines=[frappe._dict(qty=Decimal("2"), rate=Decimal("1.25"))],
		)
		self.assertEqual(evaluate_jsonata("when", data), "2026-01-15 09:30:00")
		self.assertEqual(evaluate_jsonata("day", data), "2026-01-15")
		self.assertEqual(evaluate_jsonata("amount", data), 12.5)
		self.assertEqual(evaluate_jsonata("$sum(lines.(qty * rate))", data), 2.5)

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
