# Copyright (c) 2023, Avunu LLC and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.query_builder import Interval
from frappe.query_builder.functions import Now

from espresso_sync.redaction import PULL_LOG_FIELDS, redact_pull_log_values


class EspressoSyncPullLog(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		diagnostics: DF.JSON | None
		document: DF.JSON | None
		object: DF.JSON | None
		request_type: DF.Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
		response: DF.Code | None
		sync_connection: DF.Link | None
		sync_direction: DF.Literal["Import", "Export"]
		sync_doc: DF.DynamicLink | None
		sync_doctype: DF.Link | None
		sync_status: DF.Literal["Success", "Failure"]
		traceback: DF.Code | None
		transform: DF.Link | None
		transform_hash: DF.Data | None
		url: DF.Data | None
	# end: auto-generated types

	def validate(self):
		# never store the credentials the request was sent with
		values = {field: self.get(field) for field in PULL_LOG_FIELDS}
		self.update(redact_pull_log_values(values, self.sync_connection))

	@staticmethod
	def clear_old_logs(days=30):
		"""Log Settings' retention: default_log_clearing_doctypes sets the days."""
		table = frappe.qb.DocType("Espresso Sync Pull Log")
		frappe.db.delete(table, filters=(table.creation < (Now() - Interval(days=days))))
