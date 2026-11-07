# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""Scrub credentials from Pull Log rows written before redaction existed,
and from the Error Log rows written when such a Pull Log failed to save."""

import re

import frappe

from espresso_sync.redaction import PULL_LOG_FIELDS, redact_pull_log_values

BATCH_SIZE = 500
PULL_LOG_ERROR_TITLE = "Error saving pull log"
# the failed Pull Log was logged as the repr of its as_dict()
LOGGED_CONNECTION = re.compile(r"""['"]sync_connection['"]:\s*['"]([^'"]*)['"]""")


def execute():
	secrets_cache = {}
	scrub_pull_logs(secrets_cache)
	scrub_pull_log_error_logs(secrets_cache)


def batches(doctype, fields, filters=None):
	last_name = ""
	while True:
		rows = frappe.get_all(
			doctype,
			filters={**(filters or {}), "name": [">", last_name]},
			fields=["name", *fields],
			order_by="name asc",
			limit=BATCH_SIZE,
		)
		if not rows:
			break
		yield rows
		last_name = rows[-1].name


def scrub_pull_logs(secrets_cache):
	doctype = "Espresso Sync Pull Log"
	for rows in batches(doctype, ["sync_connection", *PULL_LOG_FIELDS]):
		for row in rows:
			values = {field: row.get(field) for field in PULL_LOG_FIELDS}
			redacted = redact_pull_log_values(values, row.sync_connection, secrets_cache)
			changed = {field: value for field, value in redacted.items() if value != values[field]}
			if changed:
				frappe.db.set_value(doctype, row.name, changed, update_modified=False)


def scrub_pull_log_error_logs(secrets_cache):
	doctype = "Error Log"
	for rows in batches(doctype, ["error"], {"method": PULL_LOG_ERROR_TITLE}):
		for row in rows:
			match = LOGGED_CONNECTION.search(row.error or "")
			connection_name = match.group(1) if match else None
			error = redact_pull_log_values({"traceback": row.error}, connection_name, secrets_cache)["traceback"]
			if error != row.error:
				frappe.db.set_value(doctype, row.name, "error", error, update_modified=False)
