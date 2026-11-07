# Copyright (c) 2023, Avunu LLC and contributors
# For license information, please see license.txt

import base64
import datetime
import hashlib
import json
from typing import Any, cast

import frappe
import requests
from croniter import croniter
from dateutil.parser import parse as parse_date
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_field
from frappe.model.document import Document
from frappe.utils import get_datetime, now_datetime

from espresso_sync.map_machine import extract_object, tamp_dynamic_parameter
from espresso_sync.redaction import PULL_LOG_FIELDS, redact_pull_log_values
from espresso_sync.requests_machine import REQUEST_TIMEOUT, RateLimitedSession

SHOT_DOCTYPE = "Espresso Sync Connection Shot"
# rolled back to when saving one imported document fails, so it leaves nothing half-written
IMPORT_SAVEPOINT = "espresso_sync_import"


class PullLog:
	"""The Pull Log entry being filled in for a Connection: each save() inserts a new
	Espresso Sync Pull Log from the current values, then clears what belongs to that
	entry alone. The context (DocType, direction, map, URL) carries over to the next."""

	def __init__(self, sync_connection):
		self.sync_connection = sync_connection.name
		self.sync_doctype = ""
		self.sync_direction = ""
		self.map = "{}"
		self.url = ""
		self.request_type = ""
		# the number of failures saved, for the watermarks
		self.failures = 0
		self.clear_entry()

	def clear_entry(self):
		self.sync_doc: str | None = ""
		self.sync_status = ""
		self.object = "{}"
		self.document = "{}"
		# the request and its response are stored on the entry for that request only
		self.request: str | dict[str, Any] = "{}"
		self.response = ""
		self.traceback = ""
		self.diagnostics: list[dict[str, Any]] = []

	def fail(self, code: str, message: str, origin: str = "object"):
		"""Mark the entry failed, with `message` as its traceback and a diagnostic."""
		self.sync_status = "Failure"
		self.traceback = message
		self.diagnostics.append({"severity": "error", "code": code, "message": message, "origin": origin})

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
			"diagnostics": json.dumps(self.diagnostics, indent=4, default=str) if self.diagnostics else None,
		}
		if self.sync_status == "Failure":
			self.failures += 1
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
		finally:
			self.clear_entry()


class ImportResponseError(Exception):
	"""An import request's response that cannot be imported."""

	def __init__(self, code: str, message: str, title: str, shown: str):
		super().__init__(message)
		self.code = code
		self.message = message
		# the form's error dialog: its title takes the URL, its body is `shown`
		self.title = title
		self.shown = shown


def read_import_response(shot, response: requests.Response):
	"""The objects in an import response: the status is checked before the body is read."""
	if not 200 <= response.status_code < 300:
		raise ImportResponseError(
			"http-status",
			f"HTTP {response.status_code}",
			_("Invalid Server Response for {0}"),
			response.text,
		)
	try:
		data = response.json()
	except ValueError:
		raise ImportResponseError(
			"invalid-json", "The response is not JSON", _("Invalid JSON Response from API"), response.text
		) from None
	if shot.objects_key:
		if not isinstance(data, dict) or shot.objects_key not in data:
			message = _("Objects Key {0} not found in response data").format(shot.objects_key)
			raise ImportResponseError("objects-key", message, _("Invalid Objects Key"), message)
		data = data[shot.objects_key]
	return data


def export_watermark(results, current):
	"""The new last_export, from the (modified, succeeded) of each document exported.

	It is the newest `modified` exported before the first failure (in `modified`
	order), and never moves back: a failed document stays above it, so the next
	export sends it again, together with the documents after it.
	"""
	first_failure = min((modified for modified, ok in results if not ok), default=None)
	exported = [
		modified for modified, ok in results if ok and (first_failure is None or modified < first_failure)
	]
	if not exported:
		return current
	newest = max(exported)
	return newest if current is None or newest > current else current


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
		# every request goes through it: timeout, rate limit, 429 retries
		self.session = RateLimitedSession(self.api_rate_limit)

	def validate(self):
		# a share must not let anyone else change where the credentials are sent
		if not self.flags.ignore_permissions:
			frappe.only_for("System Manager")
		self.validate_cron_rule()
		if self.pull_shot:
			self.create_custom_fields()

	def validate_cron_rule(self):
		if self.sync_frequency != "Cron":
			return
		cron_rule = self.cron_rule or ""
		if not cron_rule:
			frappe.throw(_("A Cron Rule is needed when the Sync Frequency is Cron"))
		if not croniter.is_valid(cron_rule):
			frappe.throw(_("{0} is not a valid cron rule").format(frappe.bold(cron_rule)))

	def create_custom_fields(self):
		# Ensure the 'Espresso Sync ID' child table field exists for each DocType in the shots table
		for shot in self.shots:
			ensure_sync_fields(shot.dt)

	def sync(self):
		for shot in self.shots:
			# TODO: handle deletion of objects
			# TODO: handle URI overrides
			if shot.do_import:
				self.import_shot(shot)
			if shot.do_export:
				self.process_export(shot)
		# not save(): it would write the shots' watermarks back as they were loaded
		self.db_set("last_pull", now_datetime(), update_modified=False)

	def set_watermark(self, shot, fieldname, value):
		shot.set(fieldname, value)
		frappe.db.set_value(SHOT_DOCTYPE, shot.name, fieldname, value, update_modified=False)

	def import_shot(self, shot):
		"""Import every object the shot's request(s) return. last_import moves to the start
		of this run only when nothing failed."""
		started = now_datetime()
		failures = self.pull.failures
		self.pull.sync_doctype, self.pull.sync_direction = shot.dt, "Import"
		payloads = [None]
		if shot.override_import_request and shot.request_payload:
			payloads = [
				payload.replace('""', '"')
				for payload in tamp_dynamic_parameter(shot.request_payload, shot, self)
			]
		for payload in payloads:
			self.process_import(shot, payload)
		if self.pull.failures == failures:
			self.set_watermark(shot, "last_import", started)

	def pull_import_data(self, shot, payload=None, single_pull=False):
		"""Send the shot's import request(s) and return [{"call_string", "response_data"}]
		for those that succeeded. Each request gets one Pull Log entry, holding its response.
		A failed request is logged and the next one still runs; with `single_pull` (a sample
		for the form) nothing is logged and a failure raises."""
		url = shot.get_api_url()
		# first check to see if we need to return a single URL or a list of URLs
		if single_pull:
			# grab a single doc for the dynamic parameter substitution
			doc_name = frappe.get_all(shot.dt, limit=1, pluck="name")
			urls = tamp_dynamic_parameter(url, shot, self, doc_name)[:1]
		else:
			urls = tamp_dynamic_parameter(url, shot, self)
		headers = self.get_request_headers()
		import_data = []
		for url in urls:
			call_string = f"{url}{headers}{payload}"
			if shot.override_import_request:
				method, request_url, options = shot.import_request_type, url, {"data": payload}
			else:
				method, request_url, options = "GET", shot.get_crud_uri(url, "read"), {"params": payload}
			# a map's {doctype} may have changed it for the previous request's objects
			self.pull.sync_doctype = shot.dt
			self.pull.url, self.pull.request_type = request_url, method
			self.pull.request = {"payload": payload, "headers": headers}
			try:
				response = self.session.request(
					method, request_url, headers=headers, timeout=REQUEST_TIMEOUT, **options
				)
			except requests.RequestException as e:
				if single_pull:
					raise
				self.pull.fail("request-error", f"{type(e).__name__}: {e}", origin="request")
				self.pull.save()
				continue
			self.pull.response = response.text
			try:
				response_data = read_import_response(shot, response)
			except ImportResponseError as e:
				if single_pull:
					# call_string holds the request headers, i.e. the credentials
					shown = redact_pull_log_values({"url": request_url, "response": e.shown}, self.name)
					frappe.throw(shown["response"], title=e.title.format(shown["url"]))
				self.pull.fail(e.code, e.message, origin="request")
				self.pull.save()
				continue
			if not single_pull:
				self.pull.sync_status = "Success"
				self.pull.save()
			import_data.append({"call_string": call_string, "response_data": response_data})
		return import_data

	def process_export(self, shot):
		doctype = shot.dt
		self.pull.sync_doctype, self.pull.sync_direction = doctype, "Export"
		mapping_template = json.loads(shot.object_map_export)
		self.pull.map = json.dumps(mapping_template, indent=4)
		last_export = get_datetime(shot.last_export) if shot.last_export else None
		# the filter below reads exclude_from_sync
		ensure_sync_fields(doctype)
		# filter out exclude_from_sync by default
		filters = [[doctype, "exclude_from_sync", "=", 0]]
		# only what changed since the last export, unless the shot changed since the last sync
		last_pull = get_datetime(self.last_pull) if self.last_pull else None
		shot_modified = get_datetime(shot.modified)
		if last_export and last_pull and shot_modified and shot_modified < last_pull:
			filters.append([doctype, "modified", ">", last_export])
		# if "Only Export Synced Documents" is checked, only sync docs that have a sync_id
		if shot.export_existing:
			filters.append(["Espresso Sync ID", "sync_connection", "=", self.name])
			filters.append(["Espresso Sync ID", "external_id", "!=", ""])
		# grab any filters from the shot
		if shot.filters:
			# shot.filters is a list of lists, we need to add each item of each list to the filters list
			filters.extend(json.loads(shot.filters))
		# the oldest change first, so the watermark can stop below the first failure
		rows = frappe.get_list(
			doctype, filters=filters, fields=["name", "modified"], order_by="modified asc", distinct=True
		)
		api_url = shot.get_api_url()
		results = []
		seen = set()
		for row in rows:
			if row.name in seen:
				continue
			seen.add(row.name)
			results.append((row.modified, self.export_document(shot, row.name, api_url, mapping_template)))
		watermark = export_watermark(results, last_export)
		if watermark != last_export:
			self.set_watermark(shot, "last_export", watermark)

	def export_document(self, shot, doc_name, api_url, mapping_template) -> bool:
		"""Export one document; False when it failed (and was logged). A document that is
		excluded, or whose map gives nothing, counts as done."""
		doctype = shot.dt
		self.pull.sync_doc = doc_name
		sync_id = frappe.db.get_value(
			"Espresso Sync ID",
			{"sync_connection": self.name, "parenttype": doctype, "parent": doc_name},
			["external_id", "dont_sync"],
			as_dict=True,
		)
		# ensure this doc is not excluded from sync
		if sync_id and sync_id.dont_sync:
			self.pull.clear_entry()
			return True
		try:
			# the URL for this document alone: a tag that gives no value (or several) must not
			# send it to another document's URL
			api_urls = tamp_dynamic_parameter(api_url, shot, self, [doc_name])
			if len(api_urls) != 1:
				self.pull.url, self.pull.request_type = api_url, ""
				self.pull.fail(
					"url-variations", f"The URL gave {len(api_urls)} variations for {doc_name}, not one"
				)
				self.pull.save()
				return False
			doc = frappe.get_doc(doctype, doc_name)
			self.pull.document = str(doc.as_json())
			doc_data = doc.as_dict()
			parsed_data = extract_object(mapping_template, doc_data, sync_connection=self, doc=doc_data)
			if not parsed_data:
				self.pull.clear_entry()
				return True
			return self.export_doc(
				shot, doc, parsed_data, api_urls[0], sync_id.external_id if sync_id else None
			)
		except Exception as e:
			# a timeout, or a body requests cannot send, fails this document only: the others,
			# and the external IDs already stored for them, are kept
			self.pull.fail(type(e).__name__, f"{type(e).__name__}: {e}")
			self.alert_export_failure(doctype, doc_name)
			self.pull.save()
			return False

	def export_doc(self, shot, doc, parsed_data, object_api_url, external_id) -> bool:
		"""Send one document to the external system: a PUT when it already has an
		external ID on this Connection, a POST otherwise. One Pull Log entry either way."""
		headers = self.get_request_headers()
		self.pull.request = json.dumps({"payload": parsed_data, "headers": headers}, indent=4, default=str)
		if external_id:
			# Update the existing object in the external system
			method, url = "PUT", shot.get_crud_uri(object_api_url, "update", external_id)
		else:
			# Create a new object in the external system
			method, url = "POST", shot.get_crud_uri(object_api_url, "create")
		self.pull.request_type, self.pull.url = method, url
		response = self.session.request(
			method, url, headers=headers, json=parsed_data, timeout=REQUEST_TIMEOUT
		)
		self.pull.response = response.text
		if not 200 <= response.status_code < 300:
			self.pull.fail("http-status", f"HTTP {response.status_code}", origin="request")
			self.alert_export_failure(doc.doctype, doc.name)
			self.pull.save()
			return False
		self.pull.sync_status = "Success"
		if not external_id:
			try:
				response_data = response.json()
			except ValueError:
				response_data = None
			new_id = response_data.get("id") if isinstance(response_data, dict) else None
			if new_id in (None, ""):
				self.pull.diagnostics.append(
					{
						"severity": "warning",
						"code": "no-external-id",
						"message": "The response has no id: the next export creates the object again",
						"origin": "request",
					}
				)
			else:
				# If the external system returns a unique ID, store it in the espresso_sync_id field
				doc.append("espresso_sync_ids", {"sync_connection": self.name, "external_id": new_id})
				doc.save()
				# The object now exists in the external system: a later error in this sync
				# must not roll back its ID, or the next sync would create it again.
				frappe.db.commit()  # nosemgrep: frappe-manual-commit -- external side effect already happened; persisting the external id prevents duplicate creation
		self.pull.save()
		return True

	def alert_export_failure(self, doctype, doc_name):
		frappe.publish_realtime(
			"show_alert",
			{"message": f"Error exporting {doctype}: {doc_name}", "indicator": "orange"},
			user=frappe.session.user,
		)

	def process_import(self, shot, payload=None):
		# pull the import data from the API
		for api_call in self.pull_import_data(shot, payload):
			response_data = api_call["response_data"]
			# a list of objects, or one object
			objects = response_data if isinstance(response_data, list) else [response_data]
			for i, import_object in enumerate(objects, start=1):
				self.import_object(shot, import_object, api_call["call_string"])
				# show progress on frontend
				frappe.publish_realtime(
					"import_progress",
					{"doctype": shot.dt, "progress": i, "total": len(objects)},
					user=frappe.session.user,
				)

	def import_object(self, shot, import_object, call_string):
		"""Import one object. A failure is logged and the run goes on with the next one."""
		try:
			self.process_import_object(shot, import_object, call_string)
		except Exception as e:
			self.pull.fail(type(e).__name__, f"{type(e).__name__}: {e}")
			self.pull.save()

	def process_import_object(self, shot, import_object, call_string, save=True):
		object_json = json.dumps(import_object, indent=4, default=str)
		self.pull.object = object_json
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
		# the object map is a map, or a list of maps that each make a document
		doc = None
		for single_map in object_map if isinstance(object_map, list) else [object_map]:
			self.pull.object = object_json
			self.pull.map = json.dumps(single_map, indent=4)
			parsed_data = extract_object(single_map, import_object, self)
			if parsed_data:
				doc = self.update_or_create_doc(shot, parsed_data, external_id, modified_date, save) or doc

		return doc

	def update_or_create_doc(self, shot, parsed_data, external_id, modified_date, save=True):
		"""Update the document this Connection imported as `external_id`, or create one.
		With `save` false (a test import) nothing is written: no document, no custom field,
		no Pull Log."""
		# check to see if the map contains a condition
		if "{condition}" in parsed_data:
			# conditions are specified as a list of logical tests, such as:
			# "{condition}": [
			#     "{{ billing.address_1 != shipping.address_1 }}",
			#     "{{ billing.city != shipping.city }}"
			# ]
			# the condition is evaluated as true only if all of the tests are true
			tests = parsed_data.pop("{condition}")
			# if any of the tests are not 'True', return
			if not all(test == "True" for test in tests):
				return None

		# check to see if the doctype is specified in the map
		doctype = parsed_data.pop("{doctype}", None) or shot.dt
		if save:
			ensure_sync_fields(doctype)

		# set the pull log doctype
		self.pull.sync_doctype = doctype

		# check if the map overrides the external_id
		if "{external_id}" in parsed_data:
			external_id = parsed_data.pop("{external_id}")

		# Check if a document of this doctype with a matching Sync ID already exists
		sync_id_parents = frappe.get_all(
			"Espresso Sync ID",
			filters={"sync_connection": self.name, "parenttype": doctype, "external_id": external_id},
			pluck="parent",
		)
		doc = next(
			(
				frappe.get_doc(doctype, parent)
				for parent in sync_id_parents
				if frappe.db.exists(doctype, parent)
			),
			None,
		)

		if doc:
			# update the existing doc
			doc.update(parsed_data)
		else:
			doc = frappe.new_doc(doctype)
			doc.update(parsed_data)

			# check if a document with the same name already exists
			if doc.name and frappe.db.exists(doctype, doc.name):
				# if a document with the same name exists, update that document
				doc = frappe.get_doc(doctype, doc.name)
				doc.update(parsed_data)

			# Create Espresso Sync ID child table entry
			if doc.meta.has_field("espresso_sync_ids"):
				doc.append("espresso_sync_ids", {"sync_connection": self.name, "external_id": external_id})

		if not save:
			return doc

		# validate and save the doc
		frappe.db.savepoint(IMPORT_SAVEPOINT)
		try:
			doc.run_method("validate")
			doc.save()
			self.pull.sync_status = "Success"
			self.pull.sync_doc = doc.name
		except Exception as e:
			frappe.db.rollback(save_point=IMPORT_SAVEPOINT)
			self.pull.fail(type(e).__name__, str(e))
			self.pull.sync_doc = ""
		# save the pull log entry
		finally:
			self.pull.document = doc.as_json()
			self.pull.save()
		return doc

	@frappe.whitelist()
	def get_sample_data(self, shot_name: str):
		# calls the external API with the stored credentials
		require_sync_manager(self, "write")
		# get a list of up to 10 objects from the given API endpoint
		shot = frappe.get_doc(SHOT_DOCTYPE, shot_name)
		sample_data = self.pull_import_data(shot, payload=None, single_pull=True)
		# test if the response contains a list of objects, if not, throw error
		if not sample_data or not isinstance(sample_data[0]["response_data"], list):
			frappe.throw(_("The API response should contain a list of objects"))

		return sample_data[0]["response_data"][:10]

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
		# maps the sample with the stored map; writes nothing
		require_sync_manager(self, "write")
		import_object = frappe._dict(json.loads(sample_object))
		shot = frappe.get_doc(SHOT_DOCTYPE, shot_name)
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


def ensure_sync_fields(doctype):
	"""Add the Sync tab (Exclude from Sync, Espresso Sync IDs) to `doctype` unless it has it."""
	if not frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": "exclude_from_sync"}):
		create_espresso_sync_id_custom_fields(doctype)


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
