# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""The apps screen's Espresso Sync tile, which opens the /espresso_sync page."""

from espresso_sync.portal import has_access


def check_app_permission() -> bool:
	"""Show the tile to whoever may open the page.

	Asks the page itself rather than repeating its role list here, so the tile and the
	page never disagree.
	"""
	return has_access()
