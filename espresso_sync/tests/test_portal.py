# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""The /espresso_sync page: who gets it, what it hands the browser, and how it is served."""

import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import set_request
from frappe.website.serve import get_response
from werkzeug.datastructures import Headers

from espresso_sync import portal
from espresso_sync.www.espresso_sync import index

ROUTE = "/espresso_sync"
CONNECTION = "Espresso Sync Connection"
CONNECTION_NAME = "ES Portal Test Shop"
SECRET = "portal-test-secret-never-in-the-page"
API_KEY = "X-Portal-Test-Key"

# assets.json as a build leaves it: the page must ask for its bundles by these names.
ASSETS = {
	"espresso-sync.bundle.js": "/assets/espresso_sync/dist/js/espresso-sync.bundle.T3stH4sh.js",
	"espresso-sync.bundle.css": "/assets/espresso_sync/dist/css/espresso-sync.bundle.T3stH4sh.css",
}


def make_user(email: str, roles: list[str]) -> str:
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


class TestPortalPage(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# A desk user without System Manager, and one with it.
		cls.outsider = make_user("es-portal-outsider@example.com", ["Website Manager"])
		cls.manager = make_user("es-portal-manager@example.com", ["System Manager"])
		if not frappe.db.exists(CONNECTION, CONNECTION_NAME):
			frappe.get_doc(
				{
					"doctype": CONNECTION,
					"connection_name": CONNECTION_NAME,
					"auth_type": "Header-based",
					"api_key": API_KEY,
					"api_secret": SECRET,
					"api_domain": "api.example.invalid",
					"sync_frequency": "Manual",
					"shots": [],
				}
			).insert(ignore_permissions=True)

	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.local.flags.pop, "redirect_location", None)
		# frappe.app adds these to the response; a fresh set per test shows what the page added.
		headers = patch.object(frappe.local, "response_headers", Headers(), create=True)
		headers.start()
		self.addCleanup(headers.stop)
		assets = patch("frappe.utils.get_assets_json", return_value=ASSETS)
		assets.start()
		self.addCleanup(assets.stop)

	def render(self, user: str):
		frappe.set_user(user)
		set_request(method="GET", path=ROUTE)
		response = get_response()
		return response, frappe.safe_decode(response.get_data())

	def context_for(self, user: str) -> frappe._dict:
		frappe.set_user(user)
		set_request(method="GET", path=ROUTE)
		context = frappe._dict()
		index.get_context(context)
		return context

	def test_guest_is_sent_to_core_login_and_back(self):
		frappe.set_user("Guest")
		set_request(method="GET", path=ROUTE)
		with self.assertRaises(frappe.Redirect):
			index.get_context(frappe._dict())
		self.assertEqual(frappe.local.flags.redirect_location, "/login?redirect-to=%2Fespresso_sync")

		response, _html = self.render("Guest")
		self.assertIn(response.status_code, (301, 302))
		self.assertEqual(response.headers["Location"], "/login?redirect-to=%2Fespresso_sync")

	def test_a_user_without_the_role_gets_403_with_sign_out(self):
		response, html = self.render(self.outsider)

		self.assertEqual(response.status_code, 403)
		self.assertIn("Sign out", html)
		self.assertIn('action="/api/method/web_logout"', html)
		self.assertIn(f'name="csrf_token" value="{frappe.session.data.csrf_token}"', html)
		self.assertIn(self.outsider, html)
		# A desk user is offered the desk too; the app itself is never sent.
		self.assertIn('href="/desk"', html)
		self.assertNotIn("portal_boot", html)
		self.assertNotIn("espresso-sync.bundle", html)

	def test_the_forbidden_context_carries_no_boot(self):
		context = self.context_for(self.outsider)
		self.assertTrue(context.forbidden)
		self.assertEqual(context.http_status_code, 403)
		self.assertNotIn("boot", context)

	def test_a_system_manager_gets_the_app(self):
		for user in (self.manager, "Administrator"):
			with self.subTest(user=user):
				response, html = self.render(user)
				self.assertEqual(response.status_code, 200)
				self.assertIn('<div id="app"></div>', html)
				self.assertIn(
					f'<script type="module" src="{ASSETS["espresso-sync.bundle.js"]}"></script>', html
				)
				self.assertIn(ASSETS["espresso-sync.bundle.css"], html)
				self.assertIn(f"window.csrf_token = {json.dumps(frappe.session.data.csrf_token)}", html)
				self.assertNotIn("Sign out", html)

	def test_boot_holds_the_session_and_no_connection_data(self):
		context = self.context_for(self.manager)

		self.assertFalse(context.forbidden)
		boot = context["boot"]
		self.assertEqual(set(boot), {"user", "full_name", "session_expiry"})
		self.assertEqual(boot["user"], self.manager)
		self.assertEqual(boot["session_expiry"], frappe.get_system_settings("session_expiry"))
		self.assertTrue(context.csrf_token)
		self.assertEqual(context.sitename, frappe.local.site)

		_response, html = self.render(self.manager)
		for value in (SECRET, API_KEY, CONNECTION_NAME):
			self.assertNotIn(value, json.dumps(boot))
			self.assertNotIn(value, html)

	def test_the_boot_cannot_break_out_of_its_script(self):
		frappe.db.set_value("User", self.manager, "first_name", "</script><script>alert(1)</script>")
		self.addCleanup(frappe.db.set_value, "User", self.manager, "first_name", "es-portal-manager")
		# get_fullname keeps the names it has read for the rest of the request.
		getattr(frappe.local, "fullnames", {}).pop(self.manager, None)
		_response, html = self.render(self.manager)
		self.assertNotIn("<script>alert(1)", html)
		self.assertIn("\\u003c/script\\u003e\\u003cscript\\u003ealert(1)", html)

	def test_the_page_refuses_to_be_framed(self):
		for user in (self.manager, self.outsider):
			with self.subTest(user=user):
				frappe.local.response_headers.clear()
				self.context_for(user)
				self.assertEqual(frappe.local.response_headers.get("X-Frame-Options"), "DENY")
				self.assertEqual(
					frappe.local.response_headers.get("Content-Security-Policy"), "frame-ancestors 'none'"
				)

	def test_the_page_is_never_cached(self):
		# A cached copy would hand every visitor the first one's CSRF token and boot,
		# and skip the role check.
		self.assertTrue(index.no_cache)
		_response, first = self.render(self.manager)
		first_token = frappe.session.data.csrf_token
		_response, second = self.render("Administrator")
		self.assertIn(json.dumps(first_token), first)
		self.assertNotIn(json.dumps(first_token), second)
		self.assertIn('"user": "Administrator"', second.replace('":"', '": "'))

	def test_roles_are_checked_against_the_portal_roles(self):
		frappe.set_user(self.outsider)
		set_request(method="GET", path=ROUTE)
		self.assertFalse(portal.require_login())
		with patch.object(portal, "PORTAL_ROLES", ("Website Manager",)):
			self.assertTrue(portal.require_login())
