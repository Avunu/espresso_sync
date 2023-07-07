# Copyright (c) 2023, Avunu LLC and contributors
# For license information, please see license.txt

import base64
import datetime
import hashlib
import json

import espresso_sync.sync_machine as sync_machine
import frappe
import requests
from dateutil.parser import parse as parse_date
from espresso_sync.map_machine import extract_object, tamp_dynamic_parameter
from espresso_sync.requests_machine import RateLimitedSession
from frappe.custom.doctype.custom_field.custom_field import create_custom_field
from frappe.model.document import Document


class EspressoSyncConnection(Document):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)  # This calls the init method of the superclass
        if self.api_rate_limit:
            self.session = RateLimitedSession(self.api_rate_limit)
        else:
            self.session = requests.Session()

    def validate(self):
        if self.pull_shot:
            # self.validate_espresso_api()
            self.create_custom_fields()

        # TODO: Add validation for the API URL and API Key using the built-in validation
        # def validate_espresso_api(self):
        #     credentials_entered = False
        #     if self.auth_type == 'Basic Auth':
        # 		if self.api_url and self.api_key or not self.api_secret:
        # 			frappe.throw('Please enter all the Connection API details')

    def create_custom_fields(self):
        # Get the list of DocTypes from the shots table
        doctypes = [shot.dt for shot in self.shots]

        # Ensure the 'Espresso Sync ID' child table field exists for each DocType
        for doctype in doctypes:
            # Check if the custom field already exists
            custom_field_exists = frappe.db.exists(
                'Custom Field', {'dt': doctype, 'fieldname': 'exclude_from_sync'})

            # If the custom field does not exist, create it
            if not custom_field_exists:
                create_espresso_sync_id_custom_fields(doctype)

    def sync(self):
        for shot in self.shots:
            # TODO: handle deletion of objects
            # TODO: handle URI overrides
            if shot.do_import:
                if shot.request_payload:
                    self.import_with_payload_variations(shot)
                else:
                    self.process_import(shot)
            if shot.do_export:
                self.process_export(shot)
        # update the last sync date
        self.last_pull = datetime.datetime.now()
        self.save()
        return

    def import_with_payload_variations(self, shot):
        payload = shot.request_payload
        payloads = tamp_dynamic_parameter(payload, shot, self)
        for payload in payloads:
            payload = payload.replace('''', ''')
            self.process_import(shot, payload)

    def pull_import_data(self, shot, payload=None, single_pull=False):
        url = shot.get_api_url()
        # first check to see if we need to return a single URL or a list of URLs
        if single_pull:
            # grab a single doc for the dynamic parameter substitution
            doc = frappe.get_all(shot.dt, limit=1, fields=['*'])
            urls = tamp_dynamic_parameter(url, shot, self, doc)
            urls = [urls[0]]
        else:
            urls = tamp_dynamic_parameter(url, shot, self)
        headers = self.get_request_headers()
        import_data = []
        for url in urls:
            call_string = f'{url}{headers}{payload}'
            if shot.override_import_request:
                response = self.session.request(
                    shot.import_request_type, url, headers=headers, data=payload)
            else:
                response = self.session.get(
                    url, headers=headers, params=payload)
            # test if response is valid server response, if not, throw error
            if not str(response.status_code).startswith('2'):
                error_message = f'Invalid Server Response for {call_string} - {response.text}'
                frappe.log_error('Invalid Server Response', error_message)
                frappe.throw(response.text, title='Invalid Server Response')
            # test if response is valid json, if not, throw error
            response_data = {}
            try:
                response_data = response.json()
            except ValueError:
                frappe.throw(response.text,
                             title='Invalid JSON Response from API')
            # if an objects_key is set, filter the response data to only include the objects_key value
            if shot.objects_key:
                try:
                    response_data = response_data[shot.objects_key]
                except KeyError:
                    frappe.throw(f'Objects Key {shot.objects_key} not found in response data',
                                 title='Invalid Objects Key')
            # add the response data to the import_data list
            api_call = {
                'call_string': call_string,
                'response_data': response_data
            }
            import_data.append(api_call)

        return import_data

    def process_export(self, shot, parameters=None):
        doctype = shot.dt
        mapping_template = json.loads(shot.object_map_export)
        # get the last modified timestamp of the sync connection shot
        shot_last_modified = shot.modified
        last_export = shot.last_export
        # filter out exclude_from_sync by default
        filters = [
            [doctype, 'exclude_from_sync', '=', 0]
        ]
        # if the shot was modified after the last export, re-sync all docs
        if last_export and shot_last_modified < last_export:
            filters.append([doctype, 'modified', '>', last_export])
        # grab any filters from the shot
        if shot.filters:
            filters.append(json.loads(shot.filters))
        # get the docs to export
        docs = frappe.get_list(doctype, filters=filters, pluck='name')
        # debug
        frappe.throw(str(docs),
                    title='Docs to Export')
        # loop through the docs
        api_url = shot.get_api_url()
        api_urls = tamp_dynamic_parameter(api_url, shot, self, docs)
        for doc in docs:
            # index position of the current doc in the loop
            doc_index = docs.index(doc)
            # run the self.session, pairing the url with the current doc in the loop based on index position
            object_api_url = api_urls[doc_index]
            doc = frappe.get_doc(doctype, doc.name)
            doc_data = doc.as_dict()
            parsed_data = self.extract_object(
                mapping_template, doc_data, sync_connection=self, doc=doc_data)
            # Check if the document has a unique ID for the external system
            external_id = frappe.db.get_value(doctype='Espresso Sync ID', filters={
                'sync_connection': self.name, 'parent': doc.name}, fieldname='external_id')
            if external_id:
                # Update the existing object in the external system
                object_update_url = shot.get_crud_uri(
                    object_api_url, 'update', external_id)
                response = self.session.put(
                    object_update_url, headers=self.get_request_headers(), json=parsed_data)
                # handle bad response
                if not str(response.status_code).startswith('2'):
                    frappe.publish_realtime('show_alert', {
                                            'message': f'Error exporting {doctype}: {doc.name}', 'indicator': 'orange'}, user=frappe.session.user)
                    frappe.log_error(
                        f'Error exporting {doctype}: {doc.name}', response.text)

                    # debug
                    frappe.publish_realtime(
                        'console_log', response, user=frappe.session.user)
                    # end debug

                    # TODO: figure out task updates since they are all erroring here on an undefined response

                    continue
            else:
                # Create a new object in the external system
                object_create_url = shot.get_crud_uri(
                    object_api_url, 'create')
                response = self.session.post(
                    object_create_url, headers=self.get_request_headers(), json=parsed_data)
                # If the external system returns a unique ID, store it in the espresso_sync_id field
                if str(response.status_code).startswith('2'):
                    response_data = response.json()
                    if 'id' in response_data:
                        external_id = response_data['id']
                        frappe.db.set_value('Espresso Sync ID', {
                                            'sync_connection': self.name, 'parent': doc.name}, 'external_id', external_id)
                        # Add the Espresso Sync ID to the document
                        doc.append('espresso_sync_ids', {
                            'sync_connection': self.name,
                            'external_id': external_id
                        })
                        # Save the document
                        doc.save()
                        frappe.db.commit()
                else:
                    frappe.publish_realtime('show_alert', {
                                            'message': f'Error creating {doctype} in external system', 'indicator': 'orange'}, user=frappe.session.user)
                    frappe.log_error(
                        f'Error creating {doctype} in external system', response.content)
        # update the last_export timestamp
        frappe.db.set_value('Espresso Sync Connection Shot', shot.name, 'last_export', frappe.utils.now())
        frappe.db.commit()
        return

    def process_import(self, shot, payload=None):
        # pull the import data from the API
        import_data = self.pull_import_data(shot, payload)
        for api_call in import_data:
            response_data = api_call['response_data']
            call_string = api_call['call_string']
            # test if the response contains a list of objects and run a loop to process each object
            if isinstance(response_data, list):
                i = 0
                for import_object in response_data:
                    self.process_import_object(shot, import_object, call_string)
                    # show progress on frontend
                    frappe.publish_realtime(
                        'import_progress', {'doctype': shot.dt, 'progress': i, 'total': len(import_data)}, user=frappe.session.user)
                    i += 1
            else:
                self.process_import_object(shot, response_data, call_string)
        # update the last_import timestamp
        frappe.db.set_value('Espresso Sync Connection Shot', shot.name, 'last_import', frappe.utils.now())
        return

    def process_import_object(self, shot, import_object, call_string, save=True):
        id_field = shot.id_field_map
        modified_date_field = shot.modified_date_field_map
        modified_date_format = shot.modified_date_format
        object_map = json.loads(shot.object_map_import)

        # add the import to the sync log using add_sync_log
        # espresso_sync_log = add_sync_log(self = self, call_string = call_string, sync_object = import_object, sync_direction = 'Import')

        external_id = ''
        if id_field:
            # test if the response contains an id field, if not, throw error
            try:
                external_id = import_object[id_field]
            except KeyError:
                frappe.throw(f'ID field {id_field} not found in response data',
                             title='Invalid ID Field')
        else:
            external_id = hashlib.md5(call_string.encode()).hexdigest()
        # test if the response contains a modified date field, if not, throw error
        modified_date = ''
        if modified_date_field:
            # make sure the modified date field is in the response data
            if modified_date_field in import_object:
                modified_date = import_object[modified_date_field]
            else:
                frappe.throw(f'Modified Date field {modified_date_field} not found in response data',
                             title='Invalid Modified Date Field')
            # test if the modified date field and format are valid
            if not modified_date in ['', None]:
                if not modified_date_format in ['', None]:
                    try:
                        modified_date = datetime.datetime.strptime(
                            modified_date, modified_date_format)
                    except ValueError:
                        frappe.throw(f'Modified Date value {modified_date_field} does not match format {modified_date_format}',
                                     title='Invalid Modified Date Field')
                else:
                    try:
                        modified_date = parse_date(modified_date)
                    except ValueError:
                        frappe.throw(f'Modified Date value {modified_date_field} could not be parsed as a date',
                                     title='Invalid Modified Date Field')
        parsed_data = extract_object(
            object_map, import_object, self)
        # doc = update_or_create_doc(shot, parsed_data, external_id, modified_date, save, espresso_sync_log)
        doc = self.update_or_create_doc(
            shot, parsed_data, external_id, modified_date, save)

        return doc

    def update_or_create_doc(self, shot, parsed_data, external_id, modified_date, save=True, espresso_sync_log=None):
        doc = None
        doctype = shot.dt

        # Check if a document with a matching Sync ID already exists
        sync_id_list = frappe.db.get_all('Espresso Sync ID', filters={
            'sync_connection': self.name, 'external_id': external_id},
            fields=['parent'])

        # confirm that a matching document with a matching doctype exists
        if sync_id_list:
            for sync_id_entry in sync_id_list:
                parent_exists = frappe.db.exists(doctype, sync_id_entry.parent)
                if parent_exists:
                    doc = frappe.get_doc(doctype, sync_id_entry.parent)
                    break

        if doc:
            # check if the document has been modified after the external system
            if modified_date and (doc.modified is None or doc.modified > modified_date or shot.modified > doc.modified):
                return
            else:
                # loop through every key in parsed_data and update the doc
                for key in parsed_data:
                    doc.db_set(key, parsed_data[key])

            return
        else:
            doc = frappe.new_doc(doctype)
            doc.update(parsed_data)

            # Create Espresso Sync ID child table entry
            doc.append('espresso_sync_ids', {
                'sync_connection': self.name,
                'external_id': external_id
            })
        if save:
            try:
                doc.validate()
            except Exception as e:
                frappe.log_error(f'Document not valid: {doc.name}', e)
                # add the error to the sync log
                # espresso_sync_log.error = e
                # espresso_sync_log.save()
            else:
                try:
                    doc.save()
                    frappe.db.commit()
                except Exception as e:
                    frappe.log_error(f'Document not saved: {doc.name}', e)
                    # add the error to the sync log
                    # espresso_sync_log.error = e
                    # espresso_sync_log.save()
        return doc

    @frappe.whitelist()
    def get_doctype_fields(self, doctype):
        field_list = [
            {'fieldname': df.fieldname, 'label': df.label,
                'fieldtype': df.fieldtype, 'options': df.options}
            for df in frappe.get_meta(doctype).fields
            if df.fieldtype in ['Data', 'Table', 'Text', 'Small Text', 'Link', 'Select']
        ]
        return field_list

    @frappe.whitelist()
    def get_sample_data(self, shot_name):
        # get a list of up to 10 objects from the given API endpoint
        shot = frappe.get_doc('Espresso Sync Connection Shot', shot_name)
        # get sync_connection from shot
        if not self:
            self = shot.parent
        sample_data = self.pull_import_data(shot, payload=None, single_pull=True)
        sample_data = sample_data[0]['response_data']
        # test if the response contains a list of objects, if not, throw error
        if not isinstance(sample_data, list):
            frappe.throw(sample_data.text,
                         title='JSON Response should contain a list of objects')
            sample_data = []

        return sample_data[:10]

    @frappe.whitelist()
    def get_reference_docs(self, doctype):
        # return a list of up to 10 documents of the given doctype
        # including child field values
        reference_docs = []
        # get a list of up to 10 objects from the given API endpoint
        reference_docs_names = frappe.db.get_list(
            doctype, pluck='name', limit=10)
        for doc_name in reference_docs_names:
            doc = frappe.get_doc(doctype, doc_name).as_dict()
            # remove the espresso_sync_ids field from the doc dict
            if 'espresso_sync_ids' in doc:
                del doc['espresso_sync_ids']
            reference_docs.append(doc)
        return reference_docs

    def get_request_headers(self):
        headers = {}
        if self.auth_type == 'Header-based':
            headers[self.api_key] = self.get_password(
                'api_secret')
        elif self.auth_type == 'Basic':
            credentials = f"{self.api_key}:{self.get_password('api_secret')}"
            encoded_credentials = base64.b64encode(
                credentials.encode()).decode()
            headers['Authorization'] = f'Basic {encoded_credentials}'

        # append a content-type application/json header
        headers['Content-Type'] = 'application/json'

        return headers

    pass

# API Calls
@frappe.whitelist()
def render_sample(object_map, sample_object):
    object_map = frappe._dict(json.loads(object_map))
    sample_object = frappe._dict(json.loads(sample_object))

    return extract_object(object_map, sample_object)

@frappe.whitelist()
def test_import(doc_name, shot, sample_object):
    self = frappe.get_doc('Espresso Sync Connection', doc_name)
    shot = frappe._dict(json.loads(shot))
    import_object = frappe._dict(json.loads(sample_object))
    return self.process_import_object(shot=shot, import_object=import_object, call_string='', save=False)

@frappe.whitelist()
def sync_action(doc: str):
    doc_name = frappe._dict(json.loads(doc)).name
    self = frappe.get_doc('Espresso Sync Connection', doc_name)
    self.sync()
    return self

# Custom Fields
def create_espresso_sync_id_custom_fields(doctype):
    # get the current last field of the doctype
    last_field = frappe.get_meta(doctype).fields[-1]
    # Create a new tab called 'Sync' for this table to go into
    tab_properties = {
        'doctype': doctype,
        'fieldname': 'espresso_sync_tab',
        'fieldtype': 'Tab Break',
        'label': 'Sync',
        'insert_after': last_field.fieldname
    }
    create_custom_field(doctype, tab_properties)

    # Create a new 'check' for 'Exclude from Sync'
    check_properties = {
        'doctype': doctype,
        'fieldname': 'exclude_from_sync',
        'fieldtype': 'Check',
        'label': 'Exclude from Sync',
        'insert_after': 'espresso_sync_tab',
        'parent': 'Sync',
    }
    create_custom_field(doctype, check_properties)

    # Create the 'Espresso Sync ID' child table field in the new tab
    field_properties = {
        'doctype': doctype,
        'fieldname': 'espresso_sync_ids',
        'fieldtype': 'Table',
        'label': 'Espresso Sync IDs',
        'insert_after': 'exclude_from_sync',
        'options': 'Espresso Sync ID',
        'parent': 'Sync',
    }
    create_custom_field(doctype, field_properties)