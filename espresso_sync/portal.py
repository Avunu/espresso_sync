# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""Server side of the Espresso Sync page at /espresso_sync (www/espresso_sync).

The page is a React app (www/espresso_sync/src) that reads and writes through
Frappe's own REST API and the app's whitelisted methods, each of which checks
permissions itself. What this module adds is the gate in front of the page and
the little the app needs to start:

- A Guest is sent to core's /login, coming back here once signed in, the way
  frappe/www/desk.py guards /desk. Core's login page offers whichever sign-in
  methods the site has, so nothing here knows which.
- A signed-in user without the System Manager role gets a 403 page with a
  Sign out button (core's own Not Permitted page only offers "Login", which a
  signed-in user can't use), and never the app.
- The page can't be framed by another site (clickjacking): it sends
  `X-Frame-Options: DENY` and `Content-Security-Policy: frame-ancestors 'none'`.
- The boot holds who is signed in and the session settings, and nothing about
  any Connection: the app fetches what it shows, through the permission checks.
"""

from urllib.parse import urlencode

import frappe
from frappe import _
from frappe.sessions import get_csrf_token

#: Who may use the page. The editor writes transforms that run as background
#: jobs against external systems, so it is the same role the sync endpoints require.
PORTAL_ROLES = ("System Manager",)

#: Response headers that keep the page out of frames on any other site.
FRAMING_HEADERS = {
	"X-Frame-Options": "DENY",
	"Content-Security-Policy": "frame-ancestors 'none'",
}


def deny_framing() -> None:
	"""Refuse to be shown in a frame. frappe.app adds these to the response it builds."""
	for header, value in FRAMING_HEADERS.items():
		frappe.local.response_headers.set(header, value)


def require_login() -> bool:
	"""Send a Guest to core /login and back; answer whether the signed-in user may use the page."""
	if frappe.session.user == "Guest":
		frappe.redirect(f"/login?{urlencode({'redirect-to': frappe.request.path})}")
	if frappe.session.user == "Administrator":
		return True
	return not set(PORTAL_ROLES).isdisjoint(frappe.get_roles())


def is_desk_user() -> bool:
	"""Whether the user can open the desk (a System User), so the 403 page can offer it."""
	return frappe.get_cached_value("User", frappe.session.user, "user_type") == "System User"


def set_forbidden_context(context: frappe._dict) -> None:
	"""The 403 page: who is signed in, and a Sign out form (core's web_logout is a POST)."""
	context.http_status_code = 403
	context.forbidden = True
	context.title = _("Not permitted")
	context.message = _("Espresso Sync is only for users with the {0} role.").format(_(PORTAL_ROLES[0]))
	context.user = frappe.session.user
	context.desk_user = is_desk_user()
	context.csrf_token = get_csrf_token()


def get_boot() -> dict:
	"""What the React app starts with. No Connection data, and nothing secret."""
	user = frappe.session.user
	return {
		"user": user,
		"full_name": frappe.utils.get_fullname(user),
		# The app reloads when the session would have run out (www/espresso_sync/src/portal/session.tsx).
		"session_expiry": frappe.get_system_settings("session_expiry"),
	}


def set_portal_context(context: frappe._dict) -> None:
	"""Everything index.html hands the React app."""
	context.title = _("Espresso Sync")
	context.forbidden = False
	# get_csrf_token stores a new token in the session, which saves itself.
	context.csrf_token = get_csrf_token()
	context.sitename = frappe.local.site
	context.developer_mode = bool(frappe.conf.developer_mode)
	context.boot = get_boot()
