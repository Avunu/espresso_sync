# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

import frappe
import frappe.apps
from frappe.tests import IntegrationTestCase


class TestAppsScreen(IntegrationTestCase):
	def test_hidden_from_the_apps_screen(self):
		# the entry is there for the About dialog's logo
		self.assertTrue(frappe.get_hooks("add_to_apps_screen", app_name="espresso_sync"))
		frappe.set_user("Administrator")
		self.assertIn("System Manager", frappe.get_roles())
		self.assertNotIn("espresso_sync", [app["name"] for app in frappe.apps.get_apps()])
