# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""The schema endpoints of the transform editor: API Specs (fetch, save, operations, an
operation's JSON Schema), a DocType's JSON Schema, and payload validation against either.
Each is for System Managers only."""

import json
from typing import Any, cast

import frappe
from frappe import _

from espresso_sync.schema import openapi
from espresso_sync.schema.doctype_schema import MODES, doctype_json_schema, validate_doctype_payload
from espresso_sync.utils.safe_fetch import EgressError, safe_request

SPEC = "Espresso Sync API Spec"
CONNECTION = "Espresso Sync Connection"
SPEC_FETCH_TIMEOUT = (10, 30)
# the largest text fetched for the import screen: larger than a stored spec may be
# (openapi.MAX_SPEC_BYTES), as published specs are pretty-printed and the screen saves
# them minified (GitHub's REST description is 13 MB as published, 7 MB minified)
MAX_SOURCE_BYTES = 32 * 1024 * 1024


def require_manager():
	frappe.only_for("System Manager")


def get_spec_doc(name: str, ptype: str = "read"):
	doc = frappe.get_doc(SPEC, name)
	doc.check_permission(ptype)
	return doc


def load_spec(name: str) -> dict[str, Any]:
	doc = get_spec_doc(name)
	try:
		return openapi.load_spec_text(doc.spec_json or "")
	except openapi.SpecError as e:
		frappe.throw(str(e), title=_("Invalid API Spec"))
		raise


def spec_failure(e: openapi.SpecError):
	frappe.throw(
		"<br>".join(
			[frappe.utils.escape_html(str(e)), *(frappe.utils.escape_html(error) for error in e.errors)]
		),
		title=_("Invalid API Spec"),
	)


@frappe.whitelist(methods=["POST"])
def fetch_spec_source(url: str, connection: str | None = None) -> dict[str, Any]:
	"""The text at `url` (a spec, or a file a spec refers to), fetched by the server for the
	import screen: http(s) to public addresses only, at most MAX_SOURCE_BYTES. With a
	`connection`, its credentials go along when the URL's host is its Allowed Host."""
	require_manager()
	credentials, allowed_host = None, None
	if connection:
		doc = frappe.get_doc(CONNECTION, connection)
		doc.check_permission("write")
		credentials, allowed_host = cast(Any, doc).get_credential_headers(), doc.get("allowed_host")
	try:
		response = safe_request(
			"GET",
			url,
			headers={"Accept": "application/json, application/yaml;q=0.9, text/yaml;q=0.9, */*;q=0.5"},
			credentials=credentials,
			allowed_host=allowed_host,
			max_bytes=MAX_SOURCE_BYTES,
			timeout=SPEC_FETCH_TIMEOUT,
		)
	except EgressError as e:
		frappe.throw(str(e), title=_("Not Fetched"))
		raise
	except Exception as e:
		frappe.throw(_("{0} could not be fetched: {1}").format(url, type(e).__name__), title=_("Not Fetched"))
		raise
	if not 200 <= response.status_code < 300:
		frappe.throw(_("{0} answered HTTP {1}").format(url, response.status_code), title=_("Not Fetched"))
	return {
		"url": response.url or url,
		"status": response.status_code,
		"content_type": response.headers.get("Content-Type", ""),
		"text": response.content.decode("utf-8-sig", errors="replace"),
	}


@frappe.whitelist(methods=["POST"])
def save_spec(
	spec_json: str,
	title: str,
	connection: str | None = None,
	source_url: str | None = None,
	source_format: str | None = None,
	original_version: str | None = None,
	name: str | None = None,
) -> dict[str, Any]:
	"""Store an OpenAPI 3.1 spec, bundled (the import screen upgrades Swagger 2.0 and
	OpenAPI 3.0 and bundles external references first). Anything else is refused. With
	`name`, that API Spec is updated."""
	require_manager()
	try:
		spec = openapi.validate_canonical(openapi.load_spec_text(spec_json))
	except openapi.SpecError as e:
		spec_failure(e)
		raise
	if name:
		doc = get_spec_doc(name, "write")
	else:
		doc = frappe.new_doc(SPEC)
		doc.update({"title": title, "connection": connection})
	previous_hash = doc.get("spec_hash")
	doc.update(
		{
			"title": title,
			"spec_json": json.dumps(spec, ensure_ascii=False),
			"source_url": source_url,
			"source_format": source_format or "OpenAPI 3.1",
			"original_version": original_version or openapi.spec_version(spec),
		}
	)
	doc.save()
	return {
		"name": doc.name,
		"spec_hash": doc.get("spec_hash"),
		"changed": doc.get("spec_hash") != previous_hash,
		"operations": json.loads(doc.get("operations") or "[]"),
		"auth_hints": json.loads(doc.get("auth_hints") or "[]"),
	}


@frappe.whitelist()
def list_operations(spec: str) -> list[dict[str, Any]]:
	"""The operations of an API Spec: method, path, id, summary, tags, parts, parameters."""
	require_manager()
	return openapi.list_operations(load_spec(spec))


@frappe.whitelist()
def get_operation_schema(
	spec: str, method: str, path: str, part: str = "response", status: str | None = None
) -> dict[str, Any]:
	"""The JSON Schema of an operation's request body or response (references expanded,
	recursive ones as {"x-cycle": ref}), its media type and status, and the operation's
	parameters."""
	require_manager()
	document = load_spec(spec)
	try:
		where = openapi.operation_part(document, method, path, part, status)
		schema = openapi.operation_schema(document, method, path, part, where["status"])
		path_item, op, _pointer = openapi.find_operation(document, method, path)
		parameters = openapi.dereference(document, openapi.operation_parameters(document, path_item, op))
	except openapi.SpecError as e:
		spec_failure(e)
		raise
	return {
		"schema": schema,
		"media_type": where["media_type"],
		"status": where["status"],
		"parameters": parameters,
	}


def check_doctype(doctype: str, mode: str):
	if mode not in MODES:
		frappe.throw(_("{0} is not read, insert or update").format(mode))
	if not frappe.db.exists("DocType", doctype):
		frappe.throw(_("DocType {0} not found").format(doctype), frappe.DoesNotExistError)
	if frappe.get_meta(doctype).istable:
		frappe.throw(_("{0} is a child table: use the DocType it belongs to").format(doctype))
	if not frappe.has_permission(doctype, "read"):
		frappe.throw(_("Not permitted to read {0}").format(doctype), frappe.PermissionError)


@frappe.whitelist()
def get_doctype_schema(doctype: str, mode: str = "insert") -> dict[str, Any]:
	"""The JSON Schema of `doctype`'s documents as read, inserted or updated."""
	require_manager()
	check_doctype(doctype, mode)
	return doctype_json_schema(doctype, mode)


@frappe.whitelist(methods=["POST"])
def validate_payload(
	payload: str | dict | list,
	spec: str | None = None,
	method: str | None = None,
	path: str | None = None,
	part: str = "requestBody",
	status: str | None = None,
	doctype: str | None = None,
	mode: str = "insert",
) -> list[dict[str, Any]]:
	"""Diagnostics for a payload: against an API Spec operation's request body or response
	(`spec`, `method`, `path`, `part`, `status`), or against a DocType's documents
	(`doctype`, `mode`)."""
	require_manager()
	if isinstance(payload, str):
		try:
			payload = json.loads(payload)
		except ValueError:
			frappe.throw(_("The payload is not JSON"))
	if doctype:
		check_doctype(doctype, mode)
		return validate_doctype_payload(doctype, payload, mode)
	if not (spec and method and path):
		frappe.throw(_("Give a DocType, or an API Spec with a method and a path"))
	document = load_spec(cast(str, spec))
	try:
		where = openapi.operation_part(document, cast(str, method), cast(str, path), part, status)
	except openapi.SpecError as e:
		spec_failure(e)
		raise
	if where["pointer"] is None:
		return []
	return openapi.validate_payload(document, where["pointer"], payload, write=part == "requestBody")
