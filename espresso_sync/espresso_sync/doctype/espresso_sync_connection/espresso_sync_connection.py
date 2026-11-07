# Copyright (c) 2023, Avunu LLC and contributors
# For license information, please see license.txt

import base64
import datetime
import hashlib
import json
from typing import Any, cast

import frappe
import requests
from dateutil.parser import parse as parse_date
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_field
from frappe.model.document import Document

from espresso_sync.map_machine import extract_object, tamp_dynamic_parameter
from espresso_sync.redaction import PULL_LOG_FIELDS, redact_pull_log_values
from espresso_sync.requests_machine import REQUEST_TIMEOUT, RateLimitedSession


class PullLog:
	"""The Pull Log entry being filled in for a Connection: each save() inserts a new
	Espresso Sync Pull Log from the current values."""

	def __init__(self, sync_connection):
		self.sync_connection = sync_connection.name
		self.sync_doctype = ""
		self.sync_doc: str | None = ""
		self.sync_direction = ""
		self.sync_status = ""
		self.object = "{}"
		self.document = "{}"
		self.map = "{}"
		self.url = ""
		self.request_type = ""
		self.request: str | dict[str, Any] = "{}"
		self.response = "{}"
		self.traceback = ""

	def save(self):
		values = {
			"sync_connection": self.sync_connection,
			"sync_doctype": self.sync_doctype,
			"sync_doc": self.sync_doc,
			"sync_direction": self.sync_direction,
			"sync_status": self.sync_status,
			"object": self.object,
			"document": self.document,
			"map": self.map,
			"url": self.url,
			"request_type": self.request_type,
			"request": self.request,
			"response": self.response,
			"traceback": str(self.traceback or ""),
		}
		try:
			# the Pull Log redacts itself in validate, but insert() can fail before that
			values.update(
				redact_pull_log_values(
					{field: values.get(field) for field in PULL_LOG_FIELDS}, self.sync_connection
				)
			)
			frappe.get_doc({"doctype": "Espresso Sync Pull Log", **values}).insert()
		except Exception as e:
			# never the field values: they can hold the credentials of the request
			error = f"error: {e}\ntraceback: {frappe.get_traceback()}"
			try:
				error = redact_pull_log_values({"traceback": error}, self.sync_connection)["traceback"]
			except Exception:
				error = f"error: {type(e).__name__}"
			frappe.log_error(
				"Error saving pull log",
				f"{error}\nsync_connection: {self.sync_connection}"
				f"\nsync_doctype: {self.sync_doctype}\nsync_doc: {self.sync_doc}",
			)


class EspressoSyncConnection(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from espresso_sync.espresso_sync.doctype.espresso_sync_connection_shot.espresso_sync_connection_shot import (
			EspressoSyncConnectionShot,
		)

		api_base: DF.Data | None
		api_domain: DF.Data | None
		api_key: DF.Data | None
		api_rate_limit: DF.Int
		api_secret: DF.Password | None
		auth_type: DF.Literal["Header-based", "Basic"]
		connection_name: DF.Data | None
		cron_rule: DF.Data | None
		last_pull: DF.Datetime | None
		pull_shot: DF.Check
		shots: DF.Table[EspressoSyncConnectionShot]
		sync_frequency: DF.Literal["Manual", "Every Minute", "Hourly", "Daily", "Weekly", "Monthly", "Cron"]
	# end: auto-generated types

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)  # This calls the init method of the superclass
		# current pull log for the connection
		self.pull = PullLog(self)
		if self.api_rate_limit:
			self.session = RateLimitedSession(self.api_rate_limit)
		else:
			self.session = requests.Session()

	def validate(self):
		# a share must not let anyone else change where the credentials are sent
		if not self.flags.ignore_permissions:
			frappe.only_for("System Manager")
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
				"Custom Field", {"dt": doctype, "fieldname": "exclude_from_sync"}
			)

			# If the custom field does not exist, create it
			if not custom_field_exists:
				create_espresso_sync_id_custom_fields(doctype)

	def sync(self):
		for shot in self.shots:
			self.pull.sync_doctype = shot.dt
			# TODO: handle deletion of objects
			# TODO: handle URI overrides
			if shot.do_import:
				self.pull.sync_direction = "Import"
				if shot.override_import_request and shot.request_payload:
					self.import_with_payload_variations(shot)
				else:
					self.process_import(shot)
			if shot.do_export:
				self.pull.sync_direction = "Export"
				self.process_export(shot)
		# update the last sync date
		self.last_pull = datetime.datetime.now()
		self.save()
		return

	def import_with_payload_variations(self, shot):
		payload = shot.request_payload
		payloads = tamp_dynamic_parameter(payload, shot, self)
		for payload in payloads:
			payload = payload.replace('""', '"')
			# does a pull log go here? what does the payload match up with?
			self.process_import(shot, payload)

	def pull_import_data(self, shot, payload=None, single_pull=False):
		url = shot.get_api_url()
		# first check to see if we need to return a single URL or a list of URLs
		if single_pull:
			# grab a single doc for the dynamic parameter substitution
			doc_name = frappe.get_all(shot.dt, limit=1, pluck="name")
			urls = tamp_dynamic_parameter(url, shot, self, doc_name)
			urls = [urls[0]]
		else:
			urls = tamp_dynamic_parameter(url, shot, self)
		headers = self.get_request_headers()
		import_data = []
		for url in urls:
			call_string = f"{url}{headers}{payload}"
			self.pull.url = url
			self.pull.request = {"payload": payload, "headers": headers}
			if shot.override_import_request:
				self.pull.request_type = shot.import_request_type
				response = self.session.request(
					shot.import_request_type, url, headers=headers, data=payload, timeout=REQUEST_TIMEOUT
				)
			else:
				self.pull.request_type = "GET"
				url = shot.get_crud_uri(url, "read")
				response = self.session.get(url, headers=headers, params=payload, timeout=REQUEST_TIMEOUT)
			self.pull.response = json.dumps(response.json(), indent=4)
			# test if response is valid server response, if not, throw error
			if not str(response.status_code).startswith("2"):
				# call_string holds the request headers, i.e. the credentials
				shown = redact_pull_log_values({"url": url, "response": response.text}, self.name)
				frappe.throw(
					shown["response"], title=_("Invalid Server Response for {0}").format(shown["url"])
				)
				# put the error in the pull log
				self.pull.sync_status = "Failure"
				self.pull.traceback = response.text
				self.pull.save()
			# test if response is valid json, if not, throw error
			response_data = {}
			try:
				response_data = response.json()
			except ValueError:
				frappe.throw(response.text, title=_("Invalid JSON Response from API"))
				# put the error in the pull log
				self.pull.sync_status = "Failure"
				self.pull.traceback = response.text
				self.pull.save()
			# if an objects_key is set, filter the response data to only include the objects_key value
			if shot.objects_key:
				try:
					response_data = response_data[shot.objects_key]
				except KeyError:
					frappe.throw(
						_("Objects Key {0} not found in response data").format(shot.objects_key),
						title=_("Invalid Objects Key"),
					)
					# put the error in the pull log
					self.pull.sync_status = "Failure"
					self.pull.traceback = f"Objects Key {shot.objects_key} not found in response data"
					self.pull.save()
			# add the response data to the import_data list
			api_call = {"call_string": call_string, "response_data": response_data}
			import_data.append(api_call)

		return import_data

	def process_export(self, shot):
		doctype = shot.dt
		mapping_template = json.loads(shot.object_map_export)
		self.pull.map = json.dumps(mapping_template, indent=4)
		# get the last modified timestamp of the sync connection shot
		shot_last_modified = shot.modified
		last_export = shot.last_export
		# filter out exclude_from_sync by default
		filters = [[doctype, "exclude_from_sync", "=", 0]]
		# if the shot was modified after the last export, re-sync all docs
		if last_export and shot_last_modified < last_export:
			filters.append([doctype, "modified", ">", last_export])
		# if "Only Export Synced Documents" is checked, only sync docs that have a sync_id
		if shot.export_existing:
			filters.append(["Espresso Sync ID", "sync_connection", "=", self.name])
			filters.append(["Espresso Sync ID", "external_id", "!=", ""])
		# grab any filters from the shot
		if shot.filters:
			# shot.filters is a list of lists, we need to add each item of each list to the filters list
			filters.extend(json.loads(shot.filters))
		# get the docs to export
		doc_names = frappe.get_list(doctype, filters=filters, pluck="name")
		# loop through the docs
		api_url = shot.get_api_url()
		api_urls = tamp_dynamic_parameter(api_url, shot, self, doc_names)
		for doc_name in doc_names:
			self.pull.sync_doc = doc_name
			# ensure this doc is not excluded from sync
			if frappe.db.get_value(
				doctype="Espresso Sync ID",
				filters={"sync_connection": self.name, "parent": doc_name},
				fieldname="dont_sync",
			):
				continue
			# index position of the current doc in the loop
			doc_index = doc_names.index(doc_name)
			# run the self.session, pairing the url with the current doc in the loop based on index position
			object_api_url = api_urls[doc_index]
			doc = frappe.get_doc(doctype, doc_name)
			doc_data = doc.as_dict()
			self.pull.document = str(doc.as_json())
			parsed_data = extract_object(mapping_template, doc_data, sync_connection=self, doc=doc_data)
			if not parsed_data:
				continue
			# Check if the document has a unique ID for the external system
			external_id = frappe.db.get_value(
				doctype="Espresso Sync ID",
				filters={"sync_connection": self.name, "parent": doc.name},
				fieldname="external_id",
			)
			if external_id:
				# Update the existing object in the external system
				object_update_url = shot.get_crud_uri(object_api_url, "update", external_id)
				response = self.session.put(
					object_update_url,
					headers=self.get_request_headers(),
					json=parsed_data,
					timeout=REQUEST_TIMEOUT,
				)
				self.pull.request_type = "PUT"
				self.pull.request = json.dumps(
					{"payload": parsed_data, "headers": self.get_request_headers()}, indent=4
				)
				self.pull.response = json.dumps(response.json(), indent=4)
				self.pull.url = object_update_url
				# handle bad response
				if str(response.status_code).startswith("2"):
					self.pull.sync_status = "Success"
				else:
					self.pull.sync_status = "Failure"
					frappe.publish_realtime(
						"show_alert",
						{"message": f"Error exporting {doctype}: {doc.name}", "indicator": "orange"},
						user=frappe.session.user,
					)
					frappe.log_error(f"Error exporting {doctype}: {doc.name}", response.text)
					# put the error in the pull log
					self.pull.sync_status = "Failure"
					self.pull.traceback = response.text
					self.pull.save()
					# TODO: figure out task updates since they are all erroring here on an undefined response
			else:
				# Create a new object in the external system
				object_create_url = shot.get_crud_uri(object_api_url, "create")
				response = self.session.post(
					object_create_url,
					headers=self.get_request_headers(),
					json=parsed_data,
					timeout=REQUEST_TIMEOUT,
				)
				self.pull.request_type = "POST"
				self.pull.request = json.dumps(
					{"payload": parsed_data, "headers": self.get_request_headers()}, indent=4
				)
				self.pull.response = str(response.json())
				self.pull.url = object_create_url
				# If the external system returns a unique ID, store it in the espresso_sync_id field
				if str(response.status_code).startswith("2"):
					self.pull.sync_status = "Success"
					response_data = response.json()
					if "id" in response_data:
						external_id = response_data["id"]
						# frappe.db.set_value('Espresso Sync ID', {
						#                     'sync_connection': self.name, 'parent': doc.name}, 'external_id', external_id)
						# Add the Espresso Sync ID to the document
						doc.append(
							"espresso_sync_ids", {"sync_connection": self.name, "external_id": external_id}
						)
						# Save the document
						doc.save()
				else:
					self.pull.sync_status = "Failure"
					frappe.publish_realtime(
						"show_alert",
						{"message": f"Error creating {doctype} in external system", "indicator": "orange"},
						user=frappe.session.user,
					)
					self.pull.traceback = response.text
			self.pull.save()
		# update the last_export timestamp
		frappe.db.set_value("Espresso Sync Connection Shot", shot.name, "last_export", frappe.utils.now())
		return

	def process_import(self, shot, payload=None):
		# pull the import data from the API
		import_data = self.pull_import_data(shot, payload)
		for api_call in import_data:
			response_data = api_call["response_data"]
			call_string = api_call["call_string"]
			# test if the response contains a list of objects and run a loop to process each object
			if isinstance(response_data, list):
				for i, import_object in enumerate(response_data):
					self.process_import_object(shot, import_object, call_string)
					# show progress on frontend
					frappe.publish_realtime(
						"import_progress",
						{"doctype": shot.dt, "progress": i, "total": len(import_data)},
						user=frappe.session.user,
					)
			else:
				self.process_import_object(shot, response_data, call_string)
		# update the last_import timestamp
		frappe.db.set_value("Espresso Sync Connection Shot", shot.name, "last_import", frappe.utils.now())
		return

	def process_import_object(self, shot, import_object, call_string, save=True):
		self.pull.object = json.dumps(import_object, indent=4)
		id_field = shot.id_field_map
		modified_date_field = shot.modified_date_field_map
		modified_date_format = shot.modified_date_format
		object_map = json.loads(shot.object_map_import)
		self.pull.map = json.dumps(object_map, indent=4)

		external_id = ""
		if id_field:
			# test if the response contains an id field, if not, throw error
			try:
				external_id = import_object[id_field]
			except KeyError:
				frappe.throw(
					_("ID field {0} not found in response data").format(id_field), title=_("Invalid ID Field")
				)
				self.pull.sync_status = "Failure"
				self.pull.traceback = f"ID field {id_field} not found in response data"
		else:
			external_id = hashlib.md5(call_string.encode()).hexdigest()
		# test if the response contains a modified date field, if not, throw error
		modified_date = ""
		if modified_date_field:
			# make sure the modified date field is in the response data
			if modified_date_field in import_object:
				modified_date = import_object[modified_date_field]
			else:
				frappe.throw(
					_("Modified Date field {0} not found in response data").format(modified_date_field),
					title=_("Invalid Modified Date Field"),
				)
			# test if the modified date field and format are valid
			if modified_date not in ["", None]:
				if modified_date_format not in ["", None]:
					try:
						modified_date = datetime.datetime.strptime(modified_date, modified_date_format)
					except ValueError:
						frappe.throw(
							_("Modified Date value {0} does not match format {1}").format(
								modified_date_field, modified_date_format
							),
							title=_("Invalid Modified Date Field"),
						)
				else:
					try:
						modified_date = parse_date(modified_date)
					except ValueError:
						frappe.throw(
							_("Modified Date value {0} could not be parsed as a date").format(
								modified_date_field
							),
							title=_("Invalid Modified Date Field"),
						)
		# if the object map is a list, then we need to loop through each item in the list
		if isinstance(object_map, list):
			for single_map in object_map:
				self.pull.map = json.dumps(single_map, indent=4)
				parsed_data = extract_object(single_map, import_object, self)
				if parsed_data:
					doc = self.update_or_create_doc(shot, parsed_data, external_id, modified_date, save)
		else:
			parsed_data = extract_object(object_map, import_object, self)
			if parsed_data:
				doc = self.update_or_create_doc(shot, parsed_data, external_id, modified_date, save)

		return doc

	def update_or_create_doc(self, shot, parsed_data, external_id, modified_date, save=True):
		# check to see if the map contains a condition
		if "{condition}" in parsed_data:
			# conditions are specified as a list of logical tests, such as:
			# "{condition}": [
			#     "{{ billing.address_1 != shipping.address_1 }}",
			#     "{{ billing.city != shipping.city }}"
			# ]
			# the condition is evaluated as true only if all of the tests are true
			tests = parsed_data["{condition}"]
			# remove the condition from the parsed_data dict
			del parsed_data["{condition}"]
			# check if all the tests in the condition are 'True' strings
			if all(test == "True" for test in tests):
				pass
			else:
				# if any of the tests are not 'True', return
				return None

		# check to see if the doctype is specified in the map
		if "{doctype}" in parsed_data:
			doctype = parsed_data["{doctype}"]
			# remove the doctype from the parsed_data dict
			del parsed_data["{doctype}"]
			# Check if the custom field already exists for this doctype
			custom_field_exists = frappe.db.exists(
				"Custom Field", {"dt": doctype, "fieldname": "exclude_from_sync"}
			)

			# If the custom field does not exist, create it
			if not custom_field_exists:
				create_espresso_sync_id_custom_fields(doctype)
		else:
			doctype = shot.dt

		# set the pull log doctype
		self.pull.sync_doctype = doctype

		# check if the map overrides the external_id
		if "{external_id}" in parsed_data:
			external_id = parsed_data["{external_id}"]
			# remove the external_id from the parsed_data dict
			del parsed_data["{external_id}"]

		# Check if a document with a matching Sync ID already exists
		sync_id_list = frappe.db.get_all(
			"Espresso Sync ID",
			filters={"sync_connection": self.name, "external_id": external_id},
			fields=["parent"],
		)

		doc = None
		# confirm that a matching document with a matching doctype exists
		if sync_id_list:
			for sync_id_entry in sync_id_list:
				doc_exists = frappe.db.exists(doctype, sync_id_entry.parent)
				if doc_exists:
					doc = frappe.get_doc(doctype, sync_id_entry.parent)
					break

		if doc:
			# # check if the document has been modified after the external system
			# if modified_date and (doc.modified is None or doc.modified > modified_date or shot.modified > doc.modified):
			#     return
			# else:
			# update the existing doc
			try:
				doc.update(parsed_data)
				self.pull.sync_status = "Success"
				self.pull.sync_doc = doc.name
			except Exception as e:
				self.pull.sync_status = "Failure"
				self.pull.sync_doc = ""
				self.pull.traceback = str(e)
			# save the pull log entry
			finally:
				self.pull.document = doc.as_json()
				self.pull.save()
			return doc

		else:
			doc = frappe.new_doc(doctype)
			doc.update(parsed_data)

			# check if a document with the same name already exists
			if doc.name and frappe.db.exists(doctype, doc.name):
				# if a document with the same name exists, rename the document
				doc = frappe.get_doc(doctype, doc.name)
				doc.update(parsed_data)

			# Create Espresso Sync ID child table entry
			doc.append("espresso_sync_ids", {"sync_connection": self.name, "external_id": external_id})
		if save:
			# validate and save the doc
			try:
				doc.run_method("validate")
				doc.save()
				self.pull.sync_status = "Success"
				self.pull.sync_doc = doc.name
				self.pull.document = doc.as_json()
			except Exception as e:
				self.pull.sync_status = "Failure"
				self.pull.sync_doc = ""
				self.pull.document = doc.as_json()
				self.pull.traceback = str(e)
			# save the pull log entry
			finally:
				self.pull.save()
		return doc

	@frappe.whitelist()
	def get_sample_data(self, shot_name: str):
		# calls the external API with the stored credentials
		require_sync_manager(self, "write")
		# get a list of up to 10 objects from the given API endpoint
		shot = frappe.get_doc("Espresso Sync Connection Shot", shot_name)
		sample_data = self.pull_import_data(shot, payload=None, single_pull=True)
		sample_data = sample_data[0]["response_data"]
		# test if the response contains a list of objects, if not, throw error
		if not isinstance(sample_data, list):
			frappe.throw(_("The API response should contain a list of objects"))

		return sample_data[:10]

	@frappe.whitelist()
	def get_reference_docs(self, doctype: str):
		require_sync_manager(self, "read")
		# return a list of up to 10 documents of the given doctype
		# including child field values
		reference_docs = []
		# get a list of up to 10 objects from the given API endpoint
		reference_docs_names = frappe.db.get_list(doctype, pluck="name", limit=10)
		for doc_name in reference_docs_names:
			doc = frappe.get_doc(doctype, doc_name).as_dict()
			# remove the espresso_sync_ids field from the doc dict
			if "espresso_sync_ids" in doc:
				del doc["espresso_sync_ids"]
			reference_docs.append(doc)
		return reference_docs

	def get_request_headers(self):
		headers = {}
		if self.auth_type == "Header-based":
			headers[self.api_key] = self.get_password("api_secret")
		elif self.auth_type == "Basic":
			credentials = f"{self.api_key}:{self.get_password('api_secret')}"
			encoded_credentials = base64.b64encode(credentials.encode()).decode()
			headers["Authorization"] = f"Basic {encoded_credentials}"

		# append a content-type application/json header
		headers["Content-Type"] = "application/json"

		return headers

	@frappe.whitelist()
	def test_import(self, shot_name: str, sample_object: str):
		# may create custom fields and Pull Log rows
		require_sync_manager(self, "write")
		# shot = frappe._dict(json.loads(shot))
		import_object = frappe._dict(json.loads(sample_object))
		shot = frappe.get_doc("Espresso Sync Connection Shot", shot_name)
		return self.process_import_object(shot=shot, import_object=import_object, call_string="", save=False)


# API Calls


def get_connection(name: str) -> EspressoSyncConnection:
	return cast("EspressoSyncConnection", frappe.get_doc("Espresso Sync Connection", name))


def require_sync_manager(connection=None, ptype="read"):
	"""Raise frappe.PermissionError unless the caller is a System Manager
	(and, given a Connection, holds `ptype` permission on it)."""
	frappe.only_for("System Manager")
	if connection is not None:
		connection.check_permission(ptype)


@frappe.whitelist()
def get_doctype_fields(doctype: str):
	require_sync_manager()
	field_list = [
		{"fieldname": df.fieldname, "label": df.label, "fieldtype": df.fieldtype, "options": df.options}
		for df in frappe.get_meta(doctype).fields
		if df.fieldtype in ["Data", "Table", "Text", "Small Text", "Link", "Select"]
	]
	return field_list


@frappe.whitelist()
def render_sample(object_map: str, sample_object: str):
	# dynamic tags and templates in the map read arbitrary database values
	require_sync_manager()
	return extract_object(frappe._dict(json.loads(object_map)), frappe._dict(json.loads(sample_object)))


@frappe.whitelist()
def sync_action(doc: str):
	require_sync_manager()
	connection = get_connection(json.loads(doc)["name"])
	require_sync_manager(connection, "write")
	connection.sync()
	return connection


# Custom Fields


def create_espresso_sync_id_custom_fields(doctype):
	# get the current last field of the doctype
	last_field = frappe.get_meta(doctype).fields[-1]
	# Create a new tab called 'Sync' for this table to go into
	tab_properties = {
		"doctype": doctype,
		"fieldname": "espresso_sync_tab",
		"fieldtype": "Tab Break",
		"label": "Sync",
		"insert_after": last_field.fieldname,
	}
	create_custom_field(doctype, tab_properties)

	# Create a new 'check' for 'Exclude from Sync'
	check_properties = {
		"doctype": doctype,
		"fieldname": "exclude_from_sync",
		"fieldtype": "Check",
		"label": "Exclude from Sync",
		"insert_after": "espresso_sync_tab",
		"parent": "Sync",
	}
	create_custom_field(doctype, check_properties)

	# Create the 'Espresso Sync ID' child table field in the new tab
	field_properties = {
		"doctype": doctype,
		"fieldname": "espresso_sync_ids",
		"fieldtype": "Table",
		"label": "Espresso Sync IDs",
		"insert_after": "exclude_from_sync",
		"options": "Espresso Sync ID",
		"parent": "Sync",
	}
	create_custom_field(doctype, field_properties)
