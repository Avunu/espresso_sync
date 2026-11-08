# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""A Connection's sync: each shot imports through its Active import transform and exports
through its Active export transform.

An import reads the import transform's operation from the Connection's Server URL, page by
page (Next Request gives the next page's query parameters, up to Maximum Pages: an import
that stops there with pages left fails). For each page:

1. the status, then the body as JSON; unless Runtime Validation is Off, the body is
   checked against the operation's response schema, as warnings;
2. the items at the Items Pointer;
3. for each item, its id (External ID) and when it last changed (Modified): an item no
   newer than when it was last imported or exported is skipped, and so is one whose Sync
   ID row is Disabled. When the shot exports, a document changed here since it was last
   synced is not overwritten: the export sends it, and an item that changed in the API too
   fails, as a conflict;
4. the Active JSONata maps the item, and Runtime Validation checks the result against the
   DocType (Enforce: one with an error is not saved);
5. the document imported as that id before is updated (its child tables as the
   transform's Child Tables says), or a new one is inserted. Its Sync ID row records the
   document's modified, so that the next export knows the change came from the API.

An export reads the documents changed since Last Export, the oldest first. For each:

1. a document whose last change is the one this Connection synced is skipped: what was
   imported is not sent back, nor what was exported sent again;
2. the Active JSONata maps the document, and Runtime Validation checks the result against
   the operation's request body;
3. it is sent with the operation's method: the Update Transform's when the document has an
   external id and the shot has one, the Export Transform's otherwise;
4. a create's response gives the new external id (External ID), which is committed at
   once: the object exists in the API now, whatever happens to the rest of the sync;
5. when the shot imports, the import transform's Modified, read on the response of a
   create or an update, records when the object changed in the API: the next import does
   not read back what was exported.

A sync runs as Administrator, whoever queued it (scheduler.run_connection_sync): what it
reads and exports does not depend on who clicked Sync Now.

Every request, item and document gets a Pull Log entry, with the hash of what ran (the
Active JSONata and the fields a sync reads); a failure is logged, and the sync goes on
with the next one. Last Import and Last Export move only past what succeeded.
"""

import datetime
from typing import Any

import frappe
import requests
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_field
from frappe.utils import get_datetime, now_datetime

from espresso_sync.redaction import PULL_LOG_FIELDS, redact_pull_log_values
from espresso_sync.schema import openapi
from espresso_sync.schema.doctype_schema import EXCLUDED_FIELDS, validate_doctype_payload
from espresso_sync.transform import engine, validate
from espresso_sync.utils.safe_fetch import RateLimitedSession

TRANSFORM = "Espresso Sync Transform"
PULL_LOG = "Espresso Sync Pull Log"
SHOT = "Espresso Sync Connection Shot"
SYNC_ID = engine.SYNC_ID
SYNC_IDS_FIELD = engine.SYNC_IDS_FIELD
# rolled back to when saving one imported document fails, so it leaves nothing half-written
IMPORT_SAVEPOINT = "espresso_sync_import"
# keys of a mapped object that never reach the document
NOT_MAPPED = frozenset({"doctype", *EXCLUDED_FIELDS})


class SyncFailure(Exception):
	"""What fails one request, item or document: logged, and the sync goes on."""

	def __init__(self, code: str, message: str, diagnostics: list[dict[str, Any]] | None = None):
		super().__init__(message)
		self.code = code
		self.message = message
		self.diagnostics = diagnostics or []


def full_url(url: str, params: dict[str, Any] | None) -> str:
	"""The URL a request is sent to, its query included."""
	return requests.Request("GET", url, params=params).prepare().url or url


def succeeded(response: requests.Response) -> bool:
	return 200 <= response.status_code < 300


class Step:
	"""An Active transform as a sync runs it."""

	def __init__(self, name: str, connection: str, doctype: str, direction: str):
		self.transform: Any = frappe.get_doc(TRANSFORM, name)
		if self.transform.status != "Active" or not self.transform.active_compiled:
			raise SyncFailure("transform-not-active", _("{0} is not Active").format(name))
		if (self.transform.direction, self.transform.document_type) != (direction, doctype):
			raise SyncFailure(
				"transform-shot",
				_("{0} is not an {1} transform of {2}").format(name, _(direction), doctype),
			)
		self.sides = validate.Sides(self.transform)
		if self.sides.connection != connection:
			raise SyncFailure(
				"transform-connection", _("{0} is on an API Spec of another Connection").format(name)
			)
		self.connection = connection
		self.hash = self.transform.active_hash()

	@property
	def context(self) -> dict[str, Any]:
		"""What every Pull Log entry of the step carries."""
		return {
			"sync_doctype": self.transform.document_type,
			"sync_direction": self.transform.direction,
			"transform": self.transform.name,
			"transform_hash": self.hash,
		}

	def evaluate(self, fieldname: str, data: Any) -> Any:
		expression = self.transform.get(fieldname)
		return engine.evaluate(expression, data, connection=self.connection) if expression else None

	def map(self, item: Any) -> dict[str, Any]:
		output = engine.evaluate(self.transform.active_compiled, item, connection=self.connection)
		if not isinstance(output, dict):
			raise SyncFailure("not-an-object", _("The rules give {0}, not an object").format(type(output)))
		return output

	def check(self, diagnostics) -> list[dict[str, Any]]:
		"""What Runtime Validation keeps of the target schema's findings (`diagnostics`, a
		callable, is not called when it is Off). Enforce: an error fails the object."""
		if self.transform.runtime_validation == "Off":
			return []
		found = diagnostics()
		if self.transform.runtime_validation == "Enforce" and any(d["severity"] == "error" for d in found):
			raise SyncFailure("invalid-payload", _("The mapped object does not pass the schema"), found)
		return found


def failure(e: Exception, origin: str = "object") -> dict[str, Any]:
	"""A failed Pull Log entry's values for `e`."""
	if isinstance(e, SyncFailure):
		code, message, diagnostics = e.code, e.message, e.diagnostics
		traceback = frappe.get_traceback() if e.__cause__ else e.message
	else:
		code, message, diagnostics = type(e).__name__, validate.error_message(e), []
		traceback = frappe.get_traceback()
	return {
		"sync_status": "Failure",
		"traceback": traceback,
		"diagnostics": [
			*diagnostics,
			{"severity": "error", "code": code, "message": message, "origin": origin},
		],
	}


def response_diagnostics(step: Step, body: Any) -> list[dict[str, Any]]:
	"""The response schema's findings on `body`, as warnings."""
	if step.sides.pointer is None:
		return []
	return [
		{**d, "severity": "warning" if d["severity"] == "error" else d["severity"]}
		for d in openapi.validate_payload(step.sides.spec, step.sides.pointer, body)
	]


def imported_row(connection: str, doctype: str, external_id: str):
	"""The Sync ID row of the document this Connection imported as `external_id`."""
	rows = frappe.get_all(
		SYNC_ID,
		filters={"sync_connection": connection, "parenttype": doctype, "external_id": external_id},
		fields=["name", "parent", "dont_sync", "external_modified", "last_synced_modified"],
	)
	return next((row for row in rows if frappe.db.exists(doctype, row.parent)), None)


def changed_here(doctype: str, row) -> bool:
	"""Whether the document of a Sync ID row changed since this Connection last synced it,
	in a way the export sends."""
	doc = frappe.db.get_value(doctype, row.parent, ["modified", "exclude_from_sync"], as_dict=True)
	if doc.exclude_from_sync:
		return False
	return not row.last_synced_modified or doc.modified > row.last_synced_modified


def response_json(response: requests.Response) -> Any:
	"""The body of a response, None when it is not JSON."""
	try:
		return response.json()
	except ValueError:
		return None


def api_modified(imported: Step | None, body: Any):
	"""When the object last changed in the API, read on what it answered an export by the
	import transform's Modified, as an import reads it; None when that does not say."""
	if imported is None or body is None:
		return None
	try:
		modified = imported.evaluate("modified_expr", body)
		return None if modified in (None, "") else engine.system_datetime(modified)
	except Exception:
		# the object is sent whatever this gives: without it, the next import reads the
		# object again, and keeps a change made here meanwhile
		return None


def merge_rows(step: Step, doc, fieldname: str, rows: list[Any], key: str):
	"""Update the rows of `doc`'s table with the same key as a mapped row; add the others."""

	def key_of(row: Any) -> Any:
		value = engine.evaluate(key, row, connection=step.connection)
		return None if value is None else frappe.as_json(value)

	existing = {key_of(row.as_dict()): row for row in doc.get(fieldname) or []}
	for mapped in rows:
		row = existing.get(key_of(mapped))
		if row is None:
			doc.append(fieldname, mapped)
		elif isinstance(mapped, dict):
			row.update(mapped)


def update_document(step: Step, doc, output: dict[str, Any]):
	"""Set the mapped values on `doc`: a child table is replaced by the mapped rows, or,
	with Merge by Key, its rows are matched to them by the table's key expression."""
	keys = step.transform.get_child_table_keys()
	for fieldname, value in output.items():
		if fieldname in keys and isinstance(value, list):
			merge_rows(step, doc, fieldname, value, keys[fieldname])
		else:
			doc.set(fieldname, value)


def export_watermark(results, current):
	"""The new last_export, from the (modified, succeeded) of each document exported.

	It is the newest `modified` exported before the first failure (in `modified`
	order), and a failed document always stays above it, so the next export sends
	it again, together with the documents after it. It moves back only for that:
	a full export (after the shot changed) also sends documents older than it, and
	when one of those fails, the watermark goes to just below it.
	"""
	first_failure = min((modified for modified, ok in results if not ok), default=None)
	exported = [
		modified for modified, ok in results if ok and (first_failure is None or modified < first_failure)
	]
	watermark = max([*exported, current] if current is not None else exported, default=None)
	if first_failure is not None and watermark is not None and watermark >= first_failure:
		return first_failure - datetime.timedelta(microseconds=1)
	return watermark


# the Sync tab


def ensure_sync_fields(doctype: str):
	"""Add the Sync tab (Exclude from Sync, Espresso Sync IDs) to `doctype` unless it has it."""
	if frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": "exclude_from_sync"}):
		return
	last_field = frappe.get_meta(doctype).fields[-1]
	create_custom_field(
		doctype,
		{
			"fieldname": "espresso_sync_tab",
			"fieldtype": "Tab Break",
			"label": "Sync",
			"insert_after": last_field.fieldname,
		},
	)
	create_custom_field(
		doctype,
		{
			"fieldname": "exclude_from_sync",
			"fieldtype": "Check",
			"label": "Exclude from Sync",
			"insert_after": "espresso_sync_tab",
		},
	)
	create_custom_field(
		doctype,
		{
			"fieldname": SYNC_IDS_FIELD,
			"fieldtype": "Table",
			"label": "Espresso Sync IDs",
			"insert_after": "exclude_from_sync",
			"options": SYNC_ID,
		},
	)


class Run:
	"""One sync of a Connection: its rate-limited session, and the failures logged."""

	def __init__(self, connection):
		self.connection = connection
		self.session = RateLimitedSession(connection.api_rate_limit)
		self.failures = 0

	def sync(self):
		for shot in self.connection.shots:
			if shot.do_import:
				self.run_shot(shot, "Import", self.import_shot)
			if shot.do_export:
				self.run_shot(shot, "Export", self.export_shot)
		self.connection.db_set("last_pull", now_datetime(), update_modified=False)

	def run_shot(self, shot, direction: str, run):
		try:
			ensure_sync_fields(shot.dt)
			with validate.without_messages():
				run(shot)
		except Exception as e:
			# the shot cannot run (its transform is not Active, its first request cannot be
			# built...): it is logged, and the next shot runs
			self.log(sync_doctype=shot.dt, sync_direction=direction, **failure(e))

	def step(self, name: str, shot, direction: str) -> Step:
		return Step(name, self.connection.name, shot.dt, direction)

	def log(self, **values):
		"""Insert a Pull Log entry. One that cannot be inserted goes to the Error Log,
		without its values: they can hold what the request was sent with."""
		if values.get("sync_status") == "Failure":
			self.failures += 1
		for fieldname in ("object", "document"):
			if values.get(fieldname) is not None:
				values[fieldname] = frappe.as_json(values[fieldname])
		values["diagnostics"] = frappe.as_json(values["diagnostics"]) if values.get("diagnostics") else None
		values["sync_connection"] = self.connection.name
		try:
			# the Pull Log redacts itself in validate, but insert() can fail before that
			fields = {field: values[field] for field in PULL_LOG_FIELDS if field in values}
			values.update(redact_pull_log_values(fields, self.connection.name))
			frappe.get_doc({"doctype": PULL_LOG, **values}).insert(ignore_permissions=True)
		except Exception as e:
			error = redact_pull_log_values(
				{"traceback": f"error: {e}\ntraceback: {frappe.get_traceback()}"}, self.connection.name
			)["traceback"]
			frappe.log_error(
				"Error saving pull log",
				f"{error}\nsync_connection: {self.connection.name}"
				f"\nsync_doctype: {values.get('sync_doctype')}\nsync_doc: {values.get('sync_doc')}",
			)

	def send(self, step: Step, url: str, params: dict[str, Any], body: Any = None) -> requests.Response:
		return self.session.request(
			step.transform.method,
			url,
			params=params or None,
			json=body,
			headers={"Accept": "application/json"},
			credentials=self.connection.get_credential_headers(),
			allowed_host=self.connection.allowed_host,
		)

	# import

	def import_shot(self, shot):
		"""Import every item of the import transform's operation, page by page. Last Import
		moves to the start of the run only when nothing failed."""
		started = now_datetime()
		failures = self.failures
		step = self.step(shot.import_transform, shot, "Import")
		transform = step.transform
		# the parameters may read when the last complete import began
		url, query = transform.request_url(
			self.connection.server_url, {"last_import": shot.last_import}, self.connection.name
		)
		for _page in range(max(transform.max_pages, 1)):
			page = self.fetch_page(step, url, query)
			if page is None:
				break
			items, body, headers = page
			for item in items:
				self.import_item(step, shot, item)
			if not transform.next_request_expr:
				break
			try:
				next_query = step.evaluate(
					"next_request_expr", {"body": body, "headers": headers, "query": query}
				)
				if next_query is not None and not isinstance(next_query, dict):
					raise SyncFailure("next-request", _("Next Request must give an object"))
			except Exception as e:
				self.log(**step.context, url=full_url(url, query), **failure(e))
				break
			if not next_query or all(value is None for value in next_query.values()):
				break
			query = {**query, **next_query}
		else:
			# the pages left are read by the next import, from the same Last Import
			self.log(
				**step.context,
				url=full_url(url, query),
				**failure(
					SyncFailure(
						"max-pages",
						_("Maximum Pages ({0}) read, and Next Request gives another page").format(
							transform.max_pages
						),
					),
					origin="request",
				),
			)
		if self.failures == failures:
			shot.last_import = started
			frappe.db.set_value(SHOT, shot.name, "last_import", started, update_modified=False)

	def fetch_page(self, step: Step, url: str, query: dict[str, Any]):
		"""(the items, the body, the headers) of one page, its request logged with the
		response; None when it failed."""
		entry = {**step.context, "url": full_url(url, query), "request_type": step.transform.method}
		try:
			response = self.send(step, url, query)
			entry["response"] = response.text
			if not succeeded(response):
				raise SyncFailure("http-status", f"HTTP {response.status_code}")
			try:
				body = response.json()
			except ValueError:
				raise SyncFailure("invalid-json", _("The response is not JSON")) from None
			items = step.transform.read_items(body)
		except Exception as e:
			self.log(**entry, **failure(e, origin="request"))
			return None
		# the response is only checked: an API that answers otherwise than its spec says is
		# worth a look, and its items are still mapped and validated
		diagnostics = step.check(lambda: response_diagnostics(step, body))
		self.log(**entry, sync_status="Success", diagnostics=diagnostics)
		return items, body, dict(response.headers)

	def import_item(self, step: Step, shot, item: Any):
		entry = {**step.context, "object": item}
		try:
			imported = self.import_object(step, shot, item)
		except Exception as e:
			self.log(**entry, **failure(e))
			return
		if imported is not None:
			doc, diagnostics = imported
			self.log(
				**entry,
				sync_doc=doc.name,
				document=doc.as_dict(),
				sync_status="Success",
				diagnostics=diagnostics,
			)

	def import_object(self, step: Step, shot, item: Any):
		"""(the document saved, the diagnostics), or None for an item skipped."""
		doctype = shot.dt
		external_id = step.evaluate("external_id_expr", item)
		if external_id in (None, ""):
			raise SyncFailure("no-external-id", _("External ID gives nothing for this item"))
		external_id = engine.as_text(external_id)
		modified = step.evaluate("modified_expr", item)
		modified = None if modified in (None, "") else engine.system_datetime(modified)
		row = imported_row(self.connection.name, doctype, external_id)
		if row and (
			row.dont_sync or (modified and row.external_modified and modified <= row.external_modified)
		):
			return None
		if row and shot.do_export and changed_here(doctype, row):
			# not overwritten: the export sends the change made here. When the item changed in
			# the API too, the export overwrites that change, and the conflict is logged
			if modified is None:
				return None
			raise SyncFailure(
				"conflict",
				_(
					"Changed here since the last sync, and newer in the API: the export sends the change made here"
				),
			)
		output = {key: value for key, value in step.map(item).items() if key not in NOT_MAPPED}
		if row:
			doc = frappe.get_doc(doctype, row.parent)
		elif output.get("name") and frappe.db.exists(doctype, output["name"]):
			# a document named as the object maps it, which this Connection did not import
			doc = frappe.get_doc(doctype, output["name"])
		else:
			doc = None
		if doc is not None:
			output.pop("name", None)
		diagnostics = step.check(
			lambda: validate_doctype_payload(doctype, output, "insert" if doc is None else "update")
		)
		if doc is None:
			doc = frappe.new_doc(doctype)
			doc.update(output)
		else:
			update_document(step, doc, output)
		sync_row = next(
			(
				r
				for r in doc.get(SYNC_IDS_FIELD) or []
				if r.sync_connection == self.connection.name and r.external_id == external_id
			),
			None,
		) or doc.append(SYNC_IDS_FIELD, {"sync_connection": self.connection.name, "external_id": external_id})
		sync_row.external_modified = modified
		frappe.db.savepoint(IMPORT_SAVEPOINT)
		try:
			doc.save()
		except Exception as e:
			frappe.db.rollback(save_point=IMPORT_SAVEPOINT)
			# with what Runtime Validation found, which may say why
			raise SyncFailure(type(e).__name__, validate.error_message(e), diagnostics) from e
		# the change this sync made: the next export skips it
		sync_row.last_synced_modified = doc.modified
		frappe.db.set_value(
			SYNC_ID, sync_row.name, "last_synced_modified", doc.modified, update_modified=False
		)
		return doc, diagnostics

	# export

	def export_shot(self, shot):
		"""Export the documents changed since Last Export, the oldest first."""
		create = self.step(shot.export_transform, shot, "Export")
		update = self.step(shot.update_transform, shot, "Export") if shot.update_transform else create
		try:
			imported = self.step(shot.import_transform, shot, "Import") if shot.do_import else None
		except SyncFailure:
			# the import failed for it, and said why: the export goes on without its Modified
			imported = None
		doctype = shot.dt
		last_export = get_datetime(shot.last_export) if shot.last_export else None
		filters: list[list[Any]] = [[doctype, "exclude_from_sync", "=", 0]]
		# only what changed since the last export, unless the shot changed since the last sync
		last_pull = get_datetime(self.connection.last_pull) if self.connection.last_pull else None
		shot_modified = get_datetime(shot.modified)
		if last_export and last_pull and shot_modified and shot_modified < last_pull:
			filters.append([doctype, "modified", ">", last_export])
		# every document, whatever the user that queued the sync may read: Last Export moves past
		# them all
		rows = frappe.get_all(doctype, filters=filters, fields=["name", "modified"], order_by="modified asc")
		results = [(row.modified, self.export_document(create, update, imported, row.name)) for row in rows]
		watermark = export_watermark(results, last_export)
		if watermark != last_export:
			shot.last_export = watermark
			frappe.db.set_value(SHOT, shot.name, "last_export", watermark, update_modified=False)

	def export_document(self, create: Step, update: Step, imported: Step | None, name: str) -> bool:
		"""Export one document; False when it failed (and was logged). One that is Disabled,
		or whose last change was synced, counts as done."""
		doctype = create.transform.document_type
		row = frappe.db.get_value(
			SYNC_ID,
			{"sync_connection": self.connection.name, "parenttype": doctype, "parent": name},
			["name", "external_id", "dont_sync", "last_synced_modified"],
			as_dict=True,
		)
		if row and row.dont_sync:
			return True
		doc = frappe.get_doc(doctype, name)
		if row and row.last_synced_modified and get_datetime(doc.modified) <= row.last_synced_modified:
			return True
		step = update if row and row.external_id else create
		item = engine.document_item(doc)
		entry: dict[str, Any] = {**step.context, "sync_doc": name, "document": item}
		try:
			body = step.map(item)
			entry["object"] = body
			pointer = step.sides.pointer
			diagnostics = step.check(
				lambda: (
					openapi.validate_payload(step.sides.spec, pointer, body, write=True) if pointer else []
				)
			)
			url, query = step.transform.request_url(self.connection.server_url, item, self.connection.name)
			entry.update(url=full_url(url, query), request_type=step.transform.method)
			response = self.send(step, url, query, body if pointer else None)
			entry["response"] = response.text
			if not succeeded(response):
				raise SyncFailure("http-status", f"HTTP {response.status_code}")
			answered = response_json(response)
			synced = {"last_synced_modified": doc.modified}
			if (external_modified := api_modified(imported, answered)) is not None:
				synced["external_modified"] = external_modified
			if row and row.external_id:
				frappe.db.set_value(SYNC_ID, row.name, synced, update_modified=False)
			else:
				diagnostics.extend(self.record_created(step, doc, row, answered, synced))
		except Exception as e:
			self.log(**entry, **failure(e))
			return False
		self.log(**entry, sync_status="Success", diagnostics=diagnostics)
		return True

	def record_created(
		self, step: Step, doc, row, answered: Any, synced: dict[str, Any]
	) -> list[dict[str, Any]]:
		"""Store the id of the object a create made, from its response (`answered`), with
		`synced`, and commit it."""
		external_id = step.evaluate("external_id_expr", answered) if answered is not None else None
		if external_id in (None, ""):
			return [
				{
					"severity": "warning",
					"code": "no-external-id",
					"message": _(
						"External ID gives nothing for the response: the next export creates the object again"
					),
					"origin": "request",
				}
			]
		values = {"external_id": engine.as_text(external_id), **synced}
		if row:
			frappe.db.set_value(SYNC_ID, row.name, values, update_modified=False)
		else:
			# not doc.save(): it would change the document, which the next export would send
			doc.append(SYNC_IDS_FIELD, {"sync_connection": self.connection.name, **values}).db_insert()
		# The object now exists in the external system: a later error in this sync must not
		# roll back its ID, or the next sync would create it again.
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- external side effect already happened; persisting the external id prevents duplicate creation
		return []
