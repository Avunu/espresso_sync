# Copyright (c) 2023, Avunu LLC and contributors
# For license information, please see license.txt

import base64
import datetime
import frappe
import hashlib
import json
import requests
import time
from dateutil.parser import parse as parse_date
from espresso_sync.map_machine import tamp_dynamic_parameter, extract_object


def process_sync_connections():
    sync_connections = frappe.get_all(
        "Espresso Sync Connection", filters={"enabled": 1})
    for sync_connection in sync_connections:
        sync_connection_doc = frappe.get_doc(
            "Espresso Sync Connection", sync_connection.name)
        process_sync_connection(sync_connection_doc)

@frappe.whitelist()
def process_sync_connection_form_action(doc: str):
    doc_name = frappe._dict(json.loads(doc)).name
    document = frappe.get_doc("Espresso Sync Connection", doc_name)
    process_sync_connection(document)
    return document

def process_sync_connection(sync_connection):
    for shot in sync_connection.shots:
        # TODO: handle deletion of objects
        # TODO: handle URI overrides
        if shot.do_import:
            if shot.request_payload:
                import_with_payload_variations(sync_connection, shot)
            else:
                process_import(sync_connection, shot)
        if shot.do_export:
            process_export(sync_connection, shot)
    # update the last sync date
    sync_connection.last_pull = datetime.datetime.now()
    sync_connection.save()
    return

def import_with_payload_variations(sync_connection, shot):
    payload = shot.request_payload
    payloads = tamp_dynamic_parameter(payload, shot, sync_connection)
    for payload in payloads:
        payload = payload.replace('""', '"')
        process_import(sync_connection, shot, payload)

def import_with_uri_variations(sync_connection, shot):

    return

def process_import(sync_connection, shot, payload=None):
    url = shot.extract_api_url()
    urls = tamp_dynamic_parameter(url, shot, sync_connection)
    headers = get_request_headers(sync_connection)
    for url in urls:
        call_string = f"{url}{headers}{payload}"
        if shot.override_import_request:
            response = requests.request(shot.import_request_type, url, headers=headers, data=payload)
        else:
            response = requests.get(url, headers=headers, params=payload)
        # test if response is valid server response, if not, throw error
        if not str(response.status_code).startswith("2"):
            error_message = f"Invalid Server Response for {call_string} - {response.text}"
            frappe.log_error("Invalid Server Response", error_message)
            frappe.throw(response.text, title="Invalid Server Response")
        # test if response is valid json, if not, throw error
        try:
            response_data = response.json()
        except ValueError:
            frappe.throw(response.text,
                        title="Invalid JSON Response from API")
        # test if the response contains a list of objects and run a loop to process each object
        if isinstance(response_data, list):
            i = 0
            for import_object in response_data:
                process_import_object(shot, import_object, call_string)
                # show progress on frontend
                frappe.publish_realtime(
                    "import_progress", {"doctype": shot.dt, "progress": i, "total": len(response_data)}, user=frappe.session.user)
                i += 1
        else:
            process_import_object(shot, response_data, call_string)
    return

def process_import_object(shot, import_object, call_string, save=True):
    espresso_sync_connection = frappe.get_doc("Espresso Sync Connection", shot.parent)
    id_field = shot.id_field_map
    modified_date_field = shot.modified_date_field_map
    modified_date_format = shot.modified_date_format
    object_map = json.loads(shot.object_map_import)

    # add the import to the sync log using add_sync_log
    # espresso_sync_log = add_sync_log(sync_connection = espresso_sync_connection, call_string = call_string, sync_object = import_object, sync_direction = "Import")

    if id_field:
        # test if the response contains an id field, if not, throw error
        try:
            external_id = import_object[id_field]
        except KeyError:
            frappe.throw(f"ID field {id_field} not found in response data",
                        title="Invalid ID Field")
    else:
        external_id = hashlib.md5(call_string.encode()).hexdigest()
    # test if the response contains a modified date field, if not, throw error
    modified_date = None
    if modified_date_field:
        modified_date = import_object[modified_date_field]
        if not modified_date_field in import_object:
            frappe.throw(f"Modified Date field {modified_date_field} not found in response data",
                         title="Invalid Modified Date Field")
        if not modified_date_format in ["", None]:
            try:
                modified_date = datetime.datetime.strptime(
                    modified_date, modified_date_format)
            except ValueError:
                frappe.throw(f"Modified Date value {modified_date_field} does not match format {modified_date_format}",
                             title="Invalid Modified Date Field")
        else:
            try:
                modified_date = parse_date(modified_date)
            except ValueError:
                frappe.throw(f"Modified Date value {modified_date_field} could not be parsed as a date",
                             title="Invalid Modified Date Field")
    parsed_data = extract_object(object_map, import_object, espresso_sync_connection)
    # doc = update_or_create_doc(shot, parsed_data, external_id, modified_date, save, espresso_sync_log)
    doc = update_or_create_doc(shot, parsed_data, external_id, modified_date, save)

    return doc

def get_request_headers(sync_connection):
    headers = {}
    if sync_connection.auth_type == "Header-based":
        headers[sync_connection.api_key] = sync_connection.get_password(
            'api_secret')
    elif sync_connection.auth_type == "Basic":
        credentials = f"{sync_connection.api_key}:{sync_connection.get_password('api_secret')}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        headers["Authorization"] = f"Basic {encoded_credentials}"
    
    # append a content-type application/json header
    headers["Content-Type"] = "application/json"

    return headers

def update_or_create_doc(shot, parsed_data, external_id, modified_date, save=True, espresso_sync_log=None):
    doc = None
    sync_connection = shot.parent
    doctype = shot.dt

    # Check if a document with a matching Sync ID already exists
    sync_id_list = frappe.db.get_all("Espresso Sync ID", filters={
        "sync_connection": sync_connection, "external_id": external_id},
        fields=["parent"])

    # confirm that a matching document with a matching doctype exists
    if sync_id_list:
        for sync_id_entry in sync_id_list:
            parent_exists = frappe.db.exists(doctype, sync_id_entry.parent)
            if parent_exists:
                doc = frappe.get_doc(doctype, sync_id_entry.parent)
                break

    if doc:
        # check if the document has been modified after the external system
        # if modified_date and (doc.modified is None or doc.modified > modified_date or shot.modified > doc.modified):
        #     return
        # else:   
        #     doc.update(parsed_data)

        # return for now, let's not modify until we have a better way to handle this
        return
    else:
        doc = frappe.new_doc(doctype)
        doc.update(parsed_data)

        # Create Espresso Sync ID child table entry
        doc.append("espresso_sync_ids", {
            "sync_connection": sync_connection,
            "external_id": external_id
        })
    if save:
        try:
            doc.validate()
        except Exception as e:
            frappe.log_error(f"Document not valid: {doc.name}", e)
            # add the error to the sync log
            # espresso_sync_log.error = e
            # espresso_sync_log.save()
        else:
            try:
                doc.save()
                frappe.db.commit()
            except Exception as e:
                frappe.log_error(f"Document not saved: {doc.name}", e)
                # add the error to the sync log
                # espresso_sync_log.error = e
                # espresso_sync_log.save()
    return doc

def process_export(sync_connection, export_shot, parameters=None):
    api_rate_limit_per_second = sync_connection.api_rate_limit_per_second
    doctype = export_shot.dt
    mapping_template = json.loads(export_shot.object_map_export)
    # Fetch documents of the specified DocType
    # TODO: add option for only syncing docs that are already linked to the specified sync_connection
    # such as the following
    # docs = frappe.get_all(
    #     doctype, filters={"espresso_sync_id.sync_connection": sync_connection.name})
    # fetch all docs of the specified doctype
    # docs = frappe.get_all(doctype, fields=["*"]).as_dict()
    docs = frappe.get_all(doctype, fields=["*"])
    last_pull = sync_connection.last_pull
    # get the last modified timestamp of the sync connection
    sync_connection_last_modified = sync_connection.modified
    api_url = export_shot.extract_api_url()
    api_urls = tamp_dynamic_parameter(api_url, export_shot, sync_connection, docs)
    start_time = time.time()
    call_count = 0
    for doc in docs:
        # test the modified time
        # TODO: put this back in, make sure it's actually working as intended
        if last_pull and doc.modified:
            # had to switch this around to get docs modified after last_pull to sync
            if doc.modified > last_pull and doc.modified > sync_connection_last_modified:
                continue
        # index position of the current doc in the loop
        doc_index = docs.index(doc)
        # run the requests, pairing the url with the current doc in the loop based on index position
        object_api_url = api_urls[doc_index]
        doc = frappe.get_doc(doctype, doc.name)
        doc_data = doc.as_dict()
        parsed_data = extract_object(mapping_template, doc_data, sync_connection=sync_connection, doc=doc_data)
        # Check if the document has a unique ID for the external system
        external_id = frappe.db.get_value(doctype="Espresso Sync ID", filters={'sync_connection': sync_connection.name, 'parent': doc.name}, fieldname="external_id")
        if external_id:
            # Update the existing object in the external system
            object_update_url = export_shot.extract_crud_uri(object_api_url, "update", external_id)
            response = requests.put(object_update_url, headers=get_request_headers(sync_connection), json=parsed_data)
            # handle bad response
            if  not str(response.status_code).startswith('2'):
                frappe.publish_realtime('show_alert', {'message': f"Error exporting {doctype}: {doc.name}", 'indicator': 'orange'}, user=frappe.session.user)
                frappe.log_error(f"Error exporting {doctype}: {doc.name}", response.text)

                # debug
                frappe.publish_realtime('console_log', response, user=frappe.session.user)
                # end debug

                # TODO: figure out task updates since they are all erroring here on an undefined response

                continue
        else:
            # Create a new object in the external system
            object_create_url = export_shot.extract_crud_uri(object_api_url, "create")
            response = requests.post(object_create_url, headers=get_request_headers(sync_connection), json=parsed_data)
            # If the external system returns a unique ID, store it in the espresso_sync_id field
            if str(response.status_code).startswith('2'):
                response_data = response.json()
                if "id" in response_data:
                    # Why is there a loop here? This wasn't working.
                    # for response_data_item in response_data:
                    #     if "id" in response_data_item:
                    #         # Update the Espresso Sync ID field with the external ID
                    #         external_id = response_data_item["id"]
                    #         frappe.db.set_value("Espresso Sync ID", {"sync_connection": sync_connection.name, "parent": doc.name}, "external_id", external_id)
                    #         # Add the Espresso Sync ID to the document
                    #         doc.append("espresso_sync_ids", {
                    #             "sync_connection": sync_connection.name,
                    #             "external_id": external_id
                    #         })
                    #         # Save the document
                    #         save_doc(doc)
                    #     else:
                    #         # if the external system returns an error, log it
                    #         frappe.log_error(f"Error creating {doctype} in external system", response_data_item)
                    external_id = response_data["id"]
                    frappe.db.set_value("Espresso Sync ID", {"sync_connection": sync_connection.name, "parent": doc.name}, "external_id", external_id)
                    # Add the Espresso Sync ID to the document
                    doc.append("espresso_sync_ids", {
                        "sync_connection": sync_connection.name,
                        "external_id": external_id
                    })
                    # Save the document
                    doc.save()
                    frappe.db.commit()
            else:
                frappe.publish_realtime('show_alert', {'message': f"Error creating {doctype} in external system", 'indicator': 'orange'}, user=frappe.session.user)
                frappe.log_error(f"Error creating {doctype} in external system", response.content)
        call_count += 1
        if call_count >= api_rate_limit_per_second:
            time_passed = time.time() - start_time
            if time_passed < 1:
                time.sleep(1 - time_passed)
            call_count = 0
            start_time = time.time()

# function to add a log of the sync to the espresso_sync_log table on the espresso_sync_history doctype
# the table fields are timestamp, sync_connection, sync_shot, sync_doctype, sync_object, sync_document, traceback, sync_direction, and sync_status
def add_sync_log(espresso_sync_log=None, sync_connection=None, sync_shot=None, sync_doctype=None, sync_object=None, sync_document=None, traceback=None, call_string=None, sync_direction=None, sync_status=None):
    # create a new espresso_sync_log document
    if not espresso_sync_log:
        espresso_sync_log = frappe.new_doc("Espresso Sync Log")
    # set the fields
    if sync_connection:
        espresso_sync_log.sync_connection = sync_connection
    if sync_shot:
        espresso_sync_log.sync_shot = sync_shot
    if sync_doctype:
        espresso_sync_log.sync_doctype = sync_doctype
    if sync_object:
        espresso_sync_log.sync_object = sync_object
    if sync_document:
        espresso_sync_log.sync_document = sync_document
    if traceback:
        espresso_sync_log.traceback = traceback
    if call_string:
        espresso_sync_log.call_string = call_string
    if sync_direction:
        espresso_sync_log.sync_direction = sync_direction
    if sync_status:
        espresso_sync_log.sync_status = sync_status
    # save the document
    espresso_sync_log.save()
    frappe.db.commit()

    return espresso_sync_log