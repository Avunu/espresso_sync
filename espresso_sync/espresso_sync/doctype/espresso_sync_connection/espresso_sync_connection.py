# Copyright (c) 2023, Avunu LLC and contributors
# For license information, please see license.txt

import json
import frappe
from frappe.model.document import Document
from frappe.custom.doctype.custom_field.custom_field import create_custom_field
import espresso_sync.espresso_sync.sync_engine as sync_engine


class EspressoSyncConnection(Document):
	def validate(self):
		if self.pull_shot:
			self.validate_espresso_api()
			self.create_custom_fields()

	def validate_espresso_api(self):
		if not self.api_url or not self.api_key or not self.api_secret:
			frappe.throw(_("Please enter all the Connection API details"))

	def create_custom_fields(self):
		# Get the list of DocTypes from the imports table
		doctypes = [entry.import_doctype for entry in self.imports]

		# Ensure the "Espresso Sync ID" child table field exists for each DocType
		for doctype in doctypes:
			# Check if the custom field already exists
			custom_field_exists = frappe.db.exists('Custom Field', {'dt': doctype, 'fieldname': 'espresso_sync_ids'})
			
			# If the custom field does not exist, create it
			if not custom_field_exists:
				create_espresso_sync_id_custom_field(doctype)

	def sync(self):
		sync_engine.process_sync_connection(self)

	pass

@frappe.whitelist()
def sync_action(doc: str):
	doc_name = frappe._dict(json.loads(doc)).name
	doc = frappe.get_doc("Espresso Sync Connection", doc_name)
	# frappe.msgprint(doc)
	sync_engine.process_sync_connection(doc)
	return doc

def create_espresso_sync_id_custom_field(doctype):
    field_properties = {
        'doctype': doctype,
        'fieldname': 'espresso_sync_ids',
        'fieldtype': 'Table',
        'label': 'Espresso Sync IDs',
        'insert_after': 'modified_by',
        'options': 'Espresso Sync ID',
    }
    create_custom_field(doctype, field_properties)

    
@frappe.whitelist()
def get_doctype_fields(doctype):
    field_list = [
		{"fieldname": df.fieldname, "label": df.label, "fieldtype": df.fieldtype, "options": df.options}
		for df in frappe.get_meta(doctype).fields
		if df.fieldtype in ["Data", "Table", "Text", "Small Text", "Link", "Select"]
	]
    return field_list
