# Copyright (c) 2023, Avunu LLC and contributors
# For license information, please see license.txt

import base64
import datetime
import itertools
import json
import asyncio
import time
import re
import frappe
import requests
from dateutil.parser import parse as parse_date
from jsonpath_ng import jsonpath, parse


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
        if shot.do_import:
            # todo: handle advanced import requests
            # such as requests with payloads
            # and special request types
            # if shot.request_payload:
            #     process_import_with_payload(sync_connection, shot)
            # else:
            process_import(sync_connection, shot)
        if shot.do_export:
            process_export(sync_connection, shot)
    # update the last sync date
    sync_connection.last_pull = datetime.datetime.now()
    sync_connection.save()
    return

def import_with_payload_variations(sync_connection, shot):
    # Parse the payload
    payload = json.loads(shot.request_payload)
    payload_replacements = {}
    # Find all keys that start with "docs"
    for key in payload:
        if isinstance(payload[key], dict) and 'ids' in payload[key] and payload[key]['ids'].startswith('docs:'):
            doctype = payload[key]['ids'].split(':')[1]

    return

def import_with_uri_variations(sync_connection, shot):

    return

# TODO: figure out how to make this work with variations of variables in payload, headers, URI, etc.
def generate_id_variations(sync_connection, dynamic_id_fields):
    is_string = False
    # first, check if it's a string
    if isinstance(dynamic_id_fields, str):
        is_string = True
        # convert the string to a dict based on the / delimiter
        parts = dynamic_id_fields.split('/')[1:]
        dynamic_id_fields = {parts[i]: parts[i + 1] for i in range(0, len(parts), 2)}
    # generate all combinations of IDs
    dynamic_id_replacements = {}
    for key in dynamic_id_fields:
        if dynamic_id_fields[key].startswith('docs:'):
            doctype = dynamic_id_fields[key].split(':')[1]
            # Query for the IDs - USE THIS FOR PERMUTATION BUILDER
            ids = frappe.get_list(
                'Espresso Sync ID',
                filters={'parenttype': doctype,
                            'sync_connection': sync_connection.name},
                fields=['external_id']
            )
            # Store the IDs for replacement
            dynamic_id_replacements[key] = [id['external_id'] for id in ids]

    # Generate all combinations of IDs
    combinations = list(itertools.product(*dynamic_id_replacements.values()))

    # For each combination, replace the IDs in the payload and run the import step
    variations = []
    for combination in combinations:
        dynamic_id_value = dynamic_id_fields.copy()
        for key, value in zip(dynamic_id_replacements.keys(), combination):
            dynamic_id_value[key]['ids'] = [value]
        # add the variation to a list
        if is_string:
            variations.append('/'.join(dynamic_id_value))
        else:
            variations.append(dynamic_id_value)

    return variations

# This function builds a list of all possible permutations of a parameter string based on dynamic tags in the string
def permutation_builder(parameter, shot, sync_connection, is_export=False):
	docs = [0]
	if is_export:
		docs = frappe.get_all(shot.doctype)

	for doc in docs:
		half_baked_parameters = [parameter]  # Start with the original parameter
		finished_parameters = []
		while half_baked_parameters:
			parameter = half_baked_parameters.pop()  # Take the last parameter from the list
			# Find the first dynamic parameter in the parameter string
			first_dynamic_tag = re.search(r'{(.*?)}', parameter)
			if first_dynamic_tag:
				# Get everything between the dynamic tag braces
				dynamic_tag = first_dynamic_tag.group(1)
				if dynamic_tag.startswith('id:'):
					# Split the dynamic parameter on the colon
					dynamic_tag_parts = dynamic_tag.split(':')
					# Get the doctype from the dynamic parameter
					doctype = dynamic_tag_parts[1]
					# Get a list of all instances of the doc
					# if this is an export, get the doc related to the current doc
					if is_export:
						# find the fieldname of the link field that links the shot doctype to the doctype in the dynamic tag
						link_fields = frappe.get_meta(shot.doctype).get_link_fields()
						link_field = None
						for field in link_fields:
							if field.options == doctype:
								link_field = field.fieldname
						# get the doc
						dynamic_tag_doc = frappe.get_list(doctype, filters={link_field: doc.name}, fields=['name'])
						# if there is a doc, add it to the doc list
						if dynamic_tag_doc:
							dynamic_tag_doc_list = [doc[0]]
					else:
						dynamic_tag_doc_list = frappe.get_all(doctype)
					# Loop through the list of docs
					for dynamic_tag_doc in dynamic_tag_doc_list:
						try:
							# get the doc
							doc = frappe.get_doc(doctype, doc.name)
							# Get the external id of the doc for this sync_connection
							external_id = frappe.db.get_value(doctype="Espresso Sync ID", filters={'sync_connection': sync_connection.name, 'parent': doc.name}, fieldname="external_id")
							# If there is an external id, replace the dynamic parameter with the external id
							if external_id:
								new_parameter = parameter.replace(first_dynamic_tag.group(0), external_id)
								# Add the new parameter to the half_baked_parameters list
								half_baked_parameters.append(new_parameter)
						except Exception as e:
							frappe.publish_realtime('show_alert', {'message': f"Error getting external id for {doc_name}: {e}", 'indicator': 'orange'}, user=frappe.session.user)
							frappe.log_error(f"Error getting external id for {doc_name}: {e}")
							continue
				else:
					# Handle the dyno tag as jinja
					try:
						# Replace the dynamic parameter with the value
						new_parameter = parameter.replace(first_dynamic_tag.group(0), frappe.render_template(dynamic_tag, shot.as_dict()))
						# Add the new parameter to the half_baked_parameters list
						half_baked_parameters.append(new_parameter)
					except Exception as e:
						frappe.publish_realtime('show_alert', {'message': f"Error rendering template: {e}", 'indicator': 'orange'}, user=frappe.session.user)
						frappe.log_error(f"Error rendering template: {e}")
			# If there are no dynamic parameters, add the parameter to the finished_parameters list
			else:
				finished_parameters.append(parameter)
	return finished_parameters
        
def process_import(sync_connection, shot, payload=None):
    # debug
    # frappe.throw(f"doctype: {doctype}, id_field: {id_field}, modified_date_field: {modified_date_field}, modified_date_format: {modified_date_format}")
    # TODO: render the URL using a get_url method on the shot doc
    url = sync_connection.api_url + shot.uri

    response = requests.get(
        url, headers=get_request_headers(sync_connection), params=payload)
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
            process_import_object(shot, import_object)
            # show progress on frontend
            frappe.publish_realtime(
                "import_progress", {"progress": i, "total": len(response_data)}, user=frappe.session.user)
            i += 1
    else:
        process_import_object(shot, response_data)
    return


def process_import_object(shot, import_object, save=True):
    doctype = shot.dt
    id_field = shot.id_field_map
    modified_date_field = shot.modified_date_field_map
    modified_date_format = shot.modified_date_format
    object_map = json.loads(shot.object_map_import)
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
        shot, parsed_data, external_id, modified_date, save)

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

    return headers


def parse_mapping_template(object_map, object, sync_connection=None, doc=None):
    result = {}
    for key, value in object_map.items():
        if isinstance(value, str):
            # check if the value is a JSONPath expression
            if value.startswith("$"):
                jsonpath_expr = parse(value)
                match = jsonpath_expr.find(object)
                if match:
                    result[key] = match[0].value
                else:
                    result[key] = None
            # fetch single doc values from db if string starts with "{doc:}"
            # such as "{doc:Selling Settings:default_price_list}"
            elif value.startswith("{doc:"):
                doc_value = value.strip("{}").split(":")[1:]
                result[key] = frappe.db.get_single_value(doc_value[0], doc_value[1])
            # fetch external id of linked doc if string starts with "{id:}"
            # such as "{id:project}"
            elif value.startswith("{id:"):
                id_value = value.strip("{}").split(":")[1]
                result[key] = frappe.db.get_value(doctype="Espresso Sync ID", filters={'sync_connection': sync_connection.name, 'parent': doc[id_value]}, fieldname="external_id")
            # fetch linked doc name if string starts with "{link:}"
            # such as "{link:Customer:$.clientId}"
            elif value.startswith("{link:"):
                link_value = value.strip("{}").split(":")[1:]
                jsonpath_expr = parse(link_value[1])
                match = jsonpath_expr.find(object)[0].value
                result[key] = frappe.db.get_value(doctype="Espresso Sync ID", filters={'sync_connection': sync_connection.name, 'parenttype': link_value[0], 'external_id': match}, fieldname="parent")
            # otherwise process it as a jinja template
            else:
                result[key] = frappe.render_template(value, object)
        elif isinstance(value, dict):
            match key in value:
                # function dicts
                case "match":
                    match_key = value["match"]["match-on"]
                    match_value = object.get(match_key)
                    cases = value["match"]["cases"]
                    result[key] = cases.get(match_value)
                case "foreach":
                    objects_key = value["foreach"]["objects"]
                    nested_objects = object.get(objects_key, [])
                    nested_object_map = value["foreach"]["map"]
                    result[key] = [parse_mapping_template(
                        nested_object_map, object) for object in nested_objects]
                # non-function dicts
                case _:
                    result[key] = value
        elif isinstance(value, list):
            result[key] = [parse_mapping_template(
                item, object) for item in value]
    return result


def update_or_create_doc(shot, parsed_data, external_id, modified_date, save=True):
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
        if modified_date and doc.modified > modified_date or shot.modified > doc.modified:
            return
        doc.update(parsed_data)
    else:
        doc = frappe.new_doc(doctype)
        doc.update(parsed_data)

        # Create Espresso Sync ID child table entry
        doc.append("espresso_sync_ids", {
            "sync_connection": sync_connection,
            "external_id": external_id
        })

    if save:
        doc.save()
        frappe.db.commit()

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
    docs = frappe.get_all(doctype)
    last_pull = sync_connection.last_pull
    api_url = export_shot.get_api_url()
    api_urls = permutation_builder(api_url, export_shot, sync_connection)
    for doc in docs:
        # test the modified time
        if last_pull:
            if doc.modified < last_pull:
                continue
        # index position of the current doc in the loop
        doc_index = docs.index(doc)
        # run the requests, pairing the url with the current doc in the loop based on index position
        object_api_url = api_urls[doc_index]
        doc = frappe.get_doc(doctype, doc.name)
        doc_data = doc.as_dict()
        parsed_data = parse_mapping_template(mapping_template, doc_data, sync_connection=sync_connection, doc=doc_data)
        # Check if the document has a unique ID for the external system
        external_id = frappe.db.get_value(doctype="Espresso Sync ID", filters={'sync_connection': sync_connection.name, 'parent': doc.name}, fieldname="external_id")
        if external_id:
            # Update the existing object in the external system
            # object_update_url = f"{object_update_url}/{external_id}"
            # get_crud_uri(self, url, crud_action, external_id=None)
            object_update_url = export_shot.get_crud_uri(object_api_url, "update", external_id)
            response = requests.put(
                object_update_url, headers=get_request_headers(sync_connection), json=parsed_data)
        else:
            # Create a new object in the external system
            object_create_url = export_shot.get_crud_uri(object_api_url, "create")
            response = requests.post(
                object_create_url, headers=get_request_headers(sync_connection), json=parsed_data)
            # If the external system returns a unique ID, store it in the espresso_sync_id field
            if str(response.status_code).startswith('2'):
                response_data = response.json()
                if "id" in response_data:
                    doc.append("espresso_sync_ids", {
                        "sync_connection": sync_connection.name,
                        "external_id": response_data["id"]
                    })
                    doc.save()
                    frappe.db.commit()
            # if the external system returns an error, log it
            else:
                frappe.log_error(f"Error creating {doctype} in external system", response.content)