# Copyright (c) 2023, Avunu LLC and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class EspressoSyncID(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		dont_sync: DF.Check
		external_id: DF.Data | None
		external_modified: DF.Datetime | None
		last_synced_modified: DF.Datetime | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		sync_connection: DF.Link
	# end: auto-generated types
