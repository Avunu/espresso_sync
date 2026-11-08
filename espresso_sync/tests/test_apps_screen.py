# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

import frappe
import frappe.apps
from frappe.tests import IntegrationTestCase

from espresso_sync.tests.test_portal import make_user


def apps_screen() -> dict[str, dict]:
	"""The apps screen as the current user sees it, by app."""
	frappe.local.request_cache.clear()  # get_apps answers once per request
	return {app["name"]: app for app in frappe.apps.get_apps()}


class TestAppsScreen(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")

	def test_a_system_manager_gets_the_portal(self):
		frappe.set_user(make_user("es-apps-manager@example.com", ["System Manager"]))
		entry = apps_screen()["espresso_sync"]
		self.assertEqual(entry["route"], "/espresso_sync")
		self.assertEqual(entry["logo"], "/assets/espresso_sync/images/espresso_sync-logo.svg")

	def test_hidden_from_users_the_portal_refuses(self):
		frappe.set_user(make_user("es-apps-outsider@example.com", ["Website Manager"]))
		self.assertNotIn("espresso_sync", apps_screen())
