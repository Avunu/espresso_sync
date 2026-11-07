# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

import datetime
from decimal import Decimal

import frappe
from frappe.tests import IntegrationTestCase

from espresso_sync.apps_screen import not_listed
from espresso_sync.map_machine import evaluate_jsonata, extract_object


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


class TestAppsScreen(IntegrationTestCase):
	def test_not_listed(self):
		self.assertFalse(not_listed())
