# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

import datetime

import frappe
from frappe.tests import IntegrationTestCase

from espresso_sync import demo


class TestDemo(IntegrationTestCase):
	def test_setup_is_idempotent(self):
		ctx = {"today": datetime.date(2026, 1, 15), "seed": 1, "company": None, "erpnext_demo": False}
		demo.setup(ctx)
		demo.setup(ctx)
		self.assertEqual(frappe.db.count("Espresso Sync Connection", {"name": demo.CONNECTION}), 1)
		connection = frappe.get_doc("Espresso Sync Connection", demo.CONNECTION)
		self.assertEqual(connection.get("shots")[0].dt, "ToDo")
