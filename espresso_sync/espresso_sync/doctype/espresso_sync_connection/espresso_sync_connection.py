# Copyright (c) 2023, Avunu LLC and contributors
# For license information, please see license.txt

import json
import frappe
import requests
import espresso_sync.sync_engine as sync_engine
from frappe.model.document import Document
from frappe.custom.doctype.custom_field.custom_field import create_custom_field
from espresso_sync.map_engine import tamp_dynamic_parameter, tamp_object_map


class EspressoSyncConnection(Document):
    def validate(self):
        if self.pull_shot: 
            # self.validate_espresso_api()
            self.create_custom_fields()

	# TODO: Add validation for the API URL and API Key using the built-in validation
    # def validate_espresso_api(self):
    #     credentials_entered = False
    #     if self.auth_type == "Basic Auth":
	# 		if self.api_url and self.api_key or not self.api_secret:
	# 			frappe.throw("Please enter all the Connection API details")

    def create_custom_fields(self):
        # Get the list of DocTypes from the shots table
        doctypes = [shot.dt for shot in self.shots] 

        # Ensure the "Espresso Sync ID" child table field exists for each DocType
        for doctype in doctypes:
            # Check if the custom field already exists
            custom_field_exists = frappe.db.exists(
                'Custom Field', {'dt': doctype, 'fieldname': 'espresso_sync_ids'})

            # If the custom field does not exist, create it
            if not custom_field_exists:
                create_espresso_sync_id_custom_field(doctype)

    def sync(self):
        sync_engine.process_sync_connection(self)

    @frappe.whitelist()
    def sync_action(doc: str):
        doc_name = frappe._dict(json.loads(doc)).name
        document = frappe.get_doc("Espresso Sync Connection", doc_name) 
        sync_engine.process_sync_connection(document)
        return document

    @frappe.whitelist()
    def get_doctype_fields(self, doctype):
        field_list = [
            {"fieldname": df.fieldname, "label": df.label,
                "fieldtype": df.fieldtype, "options": df.options}
            for df in frappe.get_meta(doctype).fields
            if df.fieldtype in ["Data", "Table", "Text", "Small Text", "Link", "Select"]
        ]
        return field_list

    @frappe.whitelist()
    def get_sample_data(self, shot_name):
        # get a list of up to 10 objects from the given API endpoint
        shot = frappe.get_doc("Espresso Sync Connection Shot", shot_name)
        # get sync_connection from shot
        sync_connection = frappe.get_doc("Espresso Sync Connection", shot.parent)
        # grab a single doc for the dynamic parameter substitution
        doc = frappe.get_all(shot.dt, limit=1, fields=["*"])
        url = shot.extract_api_url()
        urls = tamp_dynamic_parameter(url, shot, sync_connection, doc)
        url = shot.extract_crud_uri(urls[0], 'read')
        response = requests.get(
            url, headers=sync_engine.get_request_headers(self))
        # test if response is valid json, if not, throw error
        try:
            response_data = response.json()
        except ValueError:
            frappe.throw(response.text,
                         title="Invalid JSON Response from API")
            response_data = []

        # test if the response contains a list of objects, if not, throw error
        if not isinstance(response_data, list):
            frappe.throw(response.text,
                         title="JSON Response should contain a list of objects")
            response_data = []

        return response_data[:10]

    @frappe.whitelist()
    def get_reference_docs(self, doctype):
        # return a list of up to 10 documents of the given doctype
        # including child field values
        reference_docs = []
        # get a list of up to 10 objects from the given API endpoint
        reference_docs_names = frappe.db.get_list(
            doctype, pluck='name', limit=10)
        for doc_name in reference_docs_names:
            doc = frappe.get_doc(doctype, doc_name)
            reference_docs.append(doc.as_dict())
        return reference_docs

    @frappe.whitelist()
    def render_sample(self, object_map, sample_object):
        object_map = frappe._dict(json.loads(object_map))
        sample_object = frappe._dict(json.loads(sample_object))

        return sync_engine.tamp_object_map(object_map, sample_object)

    @frappe.whitelist()
    def test_import(self, import_step, import_object):
        import_step = frappe._dict(json.loads(import_step))
        import_object = frappe._dict(json.loads(import_object))
        return sync_engine.process_import_object(import_step, import_object, False)

    pass

def create_espresso_sync_id_custom_field(doctype):
    # Create a new tab called 'Sync' for this table to go into
    tab_properties = {
        'doctype': doctype,
        'fieldname': 'espresso_sync_tab',
        'label': 'Sync',
    }
    create_custom_field(doctype, tab_properties)

    # Create the "Espresso Sync ID" child table field in the new tab
    field_properties = {
        'doctype': doctype,
        'fieldname': 'espresso_sync_ids',
        'fieldtype': 'Table',
        'label': 'Espresso Sync IDs',
        'insert_after': 'espresso_sync_tab',
        'options': 'Espresso Sync ID',
        'parent': 'Sync',
    }
    create_custom_field(doctype, field_properties)