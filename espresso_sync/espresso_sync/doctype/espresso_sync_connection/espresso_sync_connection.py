# Copyright (c) 2023, Avunu LLC and contributors
# For license information, please see license.txt

import json
import frappe
import requests
from frappe.model.document import Document
from frappe.custom.doctype.custom_field.custom_field import create_custom_field
import espresso_sync.sync_engine as sync_engine


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
				self.create_espresso_sync_id_custom_field(doctype)

	def sync(self):
		sync_engine.process_sync_connection(self)

	@frappe.whitelist()
	def sync_action(doc: str):
		doc_name = frappe._dict(json.loads(doc)).name
		doc = frappe.get_doc("Espresso Sync Connection", doc_name)
		# frappe.msgprint(doc)
		sync_engine.process_sync_connection(doc)
		return doc

	def create_espresso_sync_id_custom_field(self, doctype):
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
	def get_doctype_fields(self, doctype):
		field_list = [
			{"fieldname": df.fieldname, "label": df.label, "fieldtype": df.fieldtype, "options": df.options}
			for df in frappe.get_meta(doctype).fields
			if df.fieldtype in ["Data", "Table", "Text", "Small Text", "Link", "Select"]
		]
		return field_list

	@frappe.whitelist()
	def get_sample_data(self, connection, get_uri):

		# debug
		# frappe.publish_realtime('console_log', args, user=frappe.session.user)

		# connection = args.get("connection")
		# get_uri = args.get("get_uri")
		# get a list of up to 10 objects from the given API endpoint
		connection = frappe.get_doc("Espresso Sync Connection", connection)
		url = connection.api_url + get_uri
		response = requests.get(url, headers=sync_engine.get_request_headers(connection))
		# test if response is valid json, if not, throw error
		try:
			response_data = response.json()
		except ValueError:
			frappe.throw(response.text,
						title="Invalid JSON Response from API")
		
		# test if the response contains a list of objects, if not, throw error
		if not isinstance(response_data, list):
			frappe.throw(response.text,
						title="JSON Response should contain a list of objects")

		return response_data[:10]

	@frappe.whitelist()
	def get_reference_docs(self, doctype):
		# return a list of up to 10 documents of the given doctype
		reference_docs = frappe.get_all(doctype, limit=10, fields=['*'])
		return reference_docs

	@frappe.whitelist()
	def render_sample(self, object_map, sample_object):
		object_map = frappe._dict(json.loads(object_map))
		sample_object = frappe._dict(json.loads(sample_object))
		
		return sync_engine.parse_mapping_template(object_map, sample_object)

	@frappe.whitelist()
	def test_import(self, import_step, import_object):
		import_step = frappe._dict(json.loads(import_step))
		import_object = frappe._dict(json.loads(import_object))
		return sync_engine.process_import_object(import_step, import_object, False)
	
	pass
