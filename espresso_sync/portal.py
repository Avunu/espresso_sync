# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""Server side of the standalone React page at /espresso_sync (www/espresso_sync).

Signing in is Frappe core's job, not the page's: a Guest is sent to core's
/login with `redirect-to`, the same way frappe/www/desk.py guards /desk.
Core's login page offers whichever providers are configured and passes
`redirect-to` into each of them, so nothing here knows or cares which
authentication method the site uses.

Front-end counterpart: www/espresso_sync/src/portal/.
"""

from urllib.parse import urlencode

import frappe
from frappe import _
from frappe.sessions import get_csrf_token

#: Who may use the page. The editor writes transforms that run as background
#: jobs against external systems, so it is the same role the sync endpoints require.
PORTAL_ROLES = ("System Manager",)

#: The DocType the page lists.
CONNECTION = "Espresso Sync Connection"


def deny_framing() -> None:
	"""Refuse to be shown in a frame on another site (clickjacking). frappe.app adds these to the response."""
	frappe.local.response_headers.set("X-Frame-Options", "DENY")
	frappe.local.response_headers.set("Content-Security-Policy", "frame-ancestors 'none'")


def require_login() -> None:
	"""Send a Guest to core /login, coming back to this page once signed in."""
	if frappe.session.user == "Guest":
		frappe.redirect(f"/login?{urlencode({'redirect-to': frappe.request.path})}")


def has_access() -> bool:
	"""Whether the signed-in user may use the page: one of PORTAL_ROLES, and read on the Connections.

	Checked here rather than left to the page's own calls, so a user without
	access never loads the page - and so its 403s can only mean the session
	ended (see SessionProvider), never "reload and be refused again".
	"""
	if set(PORTAL_ROLES).isdisjoint(frappe.get_roles()):
		return False
	return bool(frappe.has_permission(CONNECTION, "read"))


def set_forbidden_context(context: frappe._dict) -> None:
	"""The 403 page, with a Sign out link.

	Core's own Not Permitted page offers only "Login", which sends a signed-in
	user straight back here; core's /logout page signs them out instead.
	"""
	context.http_status_code = 403
	context.forbidden = True
	context.title = _("Not permitted")
	context.message = _("Espresso Sync is only for users with the {0} role.").format(_(PORTAL_ROLES[0]))
	context.user = frappe.session.user


def set_portal_context(context: frappe._dict) -> None:
	"""Fill in what index.html hands to the React app: who is signed in, and nothing about any Connection."""
	context.title = _("Espresso Sync")
	context.forbidden = False
	# get_csrf_token stores a new token in the session, which commits itself.
	context.csrf_token = get_csrf_token()
	context.sitename = frappe.local.site
	context.boot = {
		"user": frappe.session.user,
		# The React side times the session out from this and reloads the
		# page when it runs out, which lands on require_login() above.
		"session_expiry": frappe.get_system_settings("session_expiry"),
	}
