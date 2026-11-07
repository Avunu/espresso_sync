# Copyright (c) 2023, Avunu LLC and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class EspressoSyncBatch(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		documents_processed: DF.Int
		objects_processed: DF.Int
		sync_connection: DF.Link | None
	# end: auto-generated types
