# Copyright (c) 2023, Avunu LLC and contributors
# For license information, please see license.txt

import json

import frappe


@frappe.whitelist()
def process_sync_connection_form_action(doc: str):
	from espresso_sync.espresso_sync.doctype.espresso_sync_connection.espresso_sync_connection import (
		get_connection,
		require_sync_manager,
	)

	require_sync_manager()
	sync_connection = get_connection(json.loads(doc)["name"])
	require_sync_manager(sync_connection, "write")
	sync_connection.sync()
	return sync_connection
