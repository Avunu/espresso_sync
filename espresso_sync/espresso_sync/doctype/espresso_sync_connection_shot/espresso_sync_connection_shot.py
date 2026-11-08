# Copyright (c) 2023, Avunu LLC and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class EspressoSyncConnectionShot(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		do_export: DF.Check
		do_import: DF.Check
		dt: DF.Link
		export_transform: DF.Link | None
		import_transform: DF.Link | None
		last_export: DF.Datetime | None
		last_import: DF.Datetime | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		update_transform: DF.Link | None
	# end: auto-generated types
