# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""Scrub credentials from Pull Log rows written before redaction existed."""

import frappe

from espresso_sync.redaction import PULL_LOG_TEXT_FIELDS, redact_pull_log_values

BATCH_SIZE = 500


def execute():
	doctype = "Espresso Sync Pull Log"
	fields = ["name", "sync_connection", *PULL_LOG_TEXT_FIELDS]
	secrets_cache = {}
	last_name = ""
	while True:
		rows = frappe.get_all(
			doctype,
			filters={"name": [">", last_name]},
			fields=fields,
			order_by="name asc",
			limit=BATCH_SIZE,
		)
		if not rows:
			break
		for row in rows:
			values = {field: row.get(field) for field in PULL_LOG_TEXT_FIELDS}
			redacted = redact_pull_log_values(values, row.sync_connection, secrets_cache)
			changed = {field: value for field, value in redacted.items() if value != values[field]}
			if changed:
				frappe.db.set_value(doctype, row.name, changed, update_modified=False)
		last_name = rows[-1].name
