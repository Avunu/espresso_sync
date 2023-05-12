# Copyright (c) 2023, Avunu LLC and contributors
# For license information, please see license.txt

import base64
import datetime
import itertools
import json

import frappe
import requests
from dateutil.parser import parse as parse_date
from jsonpath_ng import jsonpath, parse


def process_sync_connections():
    connections = frappe.get_all(
        "Espresso Sync Connection", filters={"enabled": 1})
    for connection in connections:
        connection_doc = frappe.get_doc(
            "Espresso Sync Connection", connection.name)
        process_sync_connection(connection_doc)


def process_sync_connection(connection):
    if connection.exports:
        for export_shot in connection.exports:
            process_export(connection, export_shot)
    if connection.imports:
        for import_shot in connection.imports:
            if import_shot.request_payload:
                process_import_with_payload(connection, import_shot)
            else:
                process_import(connection, import_shot)


def process_import_with_payload(connection, import_shot):
    # Parse the payload
    payload = json.loads(import_shot.request_payload)
    payload_replacements = {}

    # Find all keys that start with "docs"
    for key in payload:
        if isinstance(payload[key], dict) and 'ids' in payload[key] and payload[key]['ids'].startswith('docs:'):
            doctype = payload[key]['ids'].split(':')[1]
            # Query for the IDs
            ids = frappe.get_list(
                'Espresso Sync ID',
                filters={'parenttype': doctype,
                         'sync_connection': connection.name},
                fields=['external_id']
            )
            # Store the IDs for replacement
            payload_replacements[key] = [id['external_id'] for id in ids]

    # Generate all combinations of IDs
    combinations = list(itertools.product(*payload_replacements.values()))

    # For each combination, replace the IDs in the payload and run the import step
    for combination in combinations:
        new_payload = payload.copy()
        for key, value in zip(payload_replacements.keys(), combination):
            new_payload[key]['ids'] = [value]

        # process the import step
        process_import(connection, import_shot, new_payload)


def process_import(connection, import_shot, payload=None):
    # debug
    # frappe.throw(f"doctype: {doctype}, id_field: {id_field}, modified_date_field: {modified_date_field}, modified_date_format: {modified_date_format}")
    url = connection.api_url + import_shot.get_uri

    response = requests.get(
        url, headers=get_request_headers(connection), params=payload)
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

    process_import_objects(import_shot, response_data)

    return


def process_import_objects(import_shot, import_objects):
    i = 0
    for import_object in import_objects:
        process_import_object(import_shot, import_object)
        # show progress on frontend
        frappe.publish_realtime(
            "import_progress", {"progress": i, "total": len(import_objects)}, user=frappe.session.user)
        i += 1
    return


def process_import_object(import_shot, import_object, save=True):
    doctype = import_shot.import_doctype
    id_field = import_shot.id_field_map
    modified_date_field = import_shot.modified_date_field_map
    modified_date_format = import_shot.modified_date_format
    object_map = json.loads(import_shot.object_map)
    # test if the response contains an id field, if not, throw error
    try:
        external_id = import_object[id_field]
    except KeyError:
        frappe.throw(f"ID field {id_field} not found in response data",
                     title="Invalid ID Field")

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

    parsed_data = parse_mapping_template(object_map, import_object)
    doc = update_or_create_doc(
        import_shot, parsed_data, external_id, modified_date, save)

    return doc


def get_request_headers(sync_connection):
    headers = {}

    if sync_connection.auth_type == "Header":
        headers[sync_connection.api_key] = sync_connection.get_password(
            'api_secret')
    elif sync_connection.auth_type == "Basic":
        credentials = f"{sync_connection.api_key}:{sync_connection.get_password('api_secret')}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        headers["Authorization"] = f"Basic {encoded_credentials}"

    return headers


def parse_mapping_template(object_map, data, connection=None, doc=None):
    result = {}
    for key, value in object_map.items():
        if isinstance(value, str):
            # check if the value is a jsonpath expression
            if value.startswith("$"):
                jsonpath_expr = parse(value)
                match = jsonpath_expr.find(data)
                if match:
                    result[key] = match[0].value
                else:
                    result[key] = None
            # fetch single doc values from db if string starts with "doc:"
            # such as "doc:Selling Settings:default_price_list"
            elif value.startswith("doc:"):
                result[key] = frappe.db.get_single_value(
                    value.split(":")[1:], value.split(":")[2])
            # fetch external id of linked doc if string starts with "id:"
            # such as "id:project"
            elif value.startswith("id:"):
                result[key] = frappe.db.get_value(doctype="Espresso Sync ID", filters={
                                                  'sync_connection': connection.name, 'parent': doc[value.split(":")[1:]]}, fieldname="external_id")
            # fetch linked doc name if string starts with "link:"
            # such as "link:Customer:$.clientId"
            elif value.startswith("link:"):
                doctype = value.split(":")[1]
                id = value.split(":")[2]
                jsonpath_expr = parse(id)
                match = jsonpath_expr.find(data)[0].value
                result[key] = frappe.db.get_value(doctype="Espresso Sync ID", filters={
                                                  'sync_connection': connection.name, 'parenttype': doctype, 'external_id': match}, fieldname="parent")
            # otherwise process it as a jinja template
            else:
                result[key] = frappe.render_template(value, data)
        elif isinstance(value, dict):
            match key in value:
                # function dicts
                case "match":
                    match_key = value["match"]["match-on"]
                    match_value = data.get(match_key)
                    cases = value["match"]["cases"]
                    result[key] = cases.get(match_value)
                case "foreach":
                    items_key = value["foreach"]["elements"]
                    nested_items = data.get(items_key, [])
                    action = value["foreach"]["map"]
                    result[key] = [parse_mapping_template(
                        action, nested_item) for nested_item in nested_items]
                # non-function dicts
                case _:
                    result[key] = value
        elif isinstance(value, list):
            result[key] = [parse_mapping_template(
                item, data) for item in value]
    # debug
    frappe.publish_realtime(
        "console_log", f"result: {result}", user=frappe.session.user)
    return result


def update_or_create_doc(import_shot, parsed_data, external_id, modified_date, save=True):
    doc = None
    sync_connection = import_shot.parent
    doctype = import_shot.import_doctype

    # Check if a document with a matching Sync ID already exists
    sync_id_list = frappe.db.get_all("Espresso Sync ID", filters={
        "sync_connection": sync_connection, "external_id": external_id},
        fields=["parent"])

    # confirm that a matching document with a maching doctype exists
    if sync_id_list:
        for sync_id_entry in sync_id_list:
            parent_exists = frappe.db.exists(doctype, sync_id_entry.parent)
            if parent_exists:
                doc = frappe.get_doc(doctype, sync_id_entry.parent)
                break

    if doc:
        # check if the document has been modified after the external system
        if modified_date and doc.modified > modified_date or import_shot.modified > doc.modified:
            return
        doc.update(parsed_data)
    else:
        doc = frappe.new_doc(doctype)
        doc.update(parsed_data)

        # Create Espresso Sync ID child table entry
        sync_id_doc = doc.append("espresso_sync_ids", {
            "sync_connection": sync_connection,
            "external_id": external_id
        })

    if save:
        doc.save()
        frappe.db.commit()

    return doc


def process_export(connection, export_shot):
    doctype = export_shot.doctype
    create_url = export_shot.create_url
    update_url = export_shot.update_url
    mapping_template = json.loads(export_shot.mapping_template)

    # Fetch documents of the specified DocType
    docs = frappe.get_all(
        doctype, filters={"espresso_sync_id.sync_connection": connection.name})

    for doc in docs:
        doc_data = frappe.get_doc(doctype, doc.name).as_dict()
        parsed_data = parse_mapping_template(mapping_template, doc_data)

        # Check if the document has a unique ID for the external system
        external_id = doc_data.get("espresso_sync_id").get("external_id")

        if external_id:
            # Update the existing object in the external system
            url = update_url.format(external_id)
            response = requests.put(
                url, headers=get_request_headers(connection), json=parsed_data)
        else:
            # Create a new object in the external system
            response = requests.post(
                create_url, headers=get_request_headers(connection), json=parsed_data)

            # If the external system returns a unique ID, store it in the espresso_sync_id field
            if response.status_code in [200, 201]:
                response_data = response.json()
                if "id" in response_data:
                    sync_id = frappe.new_doc("Espresso Sync ID")
                    sync_id.sync_connection = connection.name
                    sync_id.external_id = response_data["id"]
                    sync_id.parent = doc.name
                    sync_id.parenttype = doctype
                    sync_id.parentfield = "espresso_sync_id"
                    sync_id.save()
