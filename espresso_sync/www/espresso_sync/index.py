# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""/espresso_sync: the transform editor's page (see espresso_sync/portal.py)."""

import frappe

from espresso_sync.portal import (
	deny_framing,
	has_access,
	require_login,
	set_forbidden_context,
	set_portal_context,
)

# Each response carries the visitor's CSRF token and boot, and the access check
# must run every time: never serve it from the page cache.
no_cache = True


def get_context(context: frappe._dict) -> None:
	deny_framing()
	require_login()
	if has_access():
		set_portal_context(context)
	else:
		set_forbidden_context(context)
