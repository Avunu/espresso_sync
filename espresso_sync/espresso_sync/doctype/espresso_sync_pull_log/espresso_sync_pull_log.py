# Copyright (c) 2023, Avunu LLC and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document

from espresso_sync.redaction import PULL_LOG_FIELDS, redact_pull_log_values


class EspressoSyncPullLog(Document):
	def validate(self):
		# never store the credentials the request was sent with
		values = {field: self.get(field) for field in PULL_LOG_FIELDS}
		self.update(redact_pull_log_values(values, self.sync_connection))
