# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

import datetime
import json

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
		shot = connection.get("shots")[0]
		self.assertEqual((shot.dt, shot.import_transform), ("ToDo", demo.TRANSFORM))
		transform = frappe.get_doc("Espresso Sync Transform", demo.TRANSFORM)
		self.assertEqual(transform.get("status"), "Active")
		self.assertEqual(json.loads(transform.get("diagnostics")), [])
