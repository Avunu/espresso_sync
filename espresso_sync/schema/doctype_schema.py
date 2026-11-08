# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""The JSON Schema (draft 2020-12) of a DocType's documents, from its meta, and the
validation of a document payload against it.

The schema's shape is a contract with the transform editor (its schemaTree): each
property carries an ``x-frappe`` object with the field's type, options, link target,
Dynamic Link field, requiredness ("hard": the payload must give it; "server": Frappe
fills it in), read-only flag and whether it is a Custom Field.

The schema is what Frappe stores; the validator knows what Frappe also takes and
converts, and reports that as a warning, not an error: a number given as a string, a
Check given as a boolean (information only), an empty value.
"""

from typing import Any, cast

import frappe
from dateutil import parser as date_parser
from frappe import _
from frappe.model import default_fields, display_fieldtypes, table_fields
from frappe.utils import strip_html, validate_email_address
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from espresso_sync.schema.openapi import pointer_of

MODES = ("read", "insert", "update")
JSON_SCHEMA = "https://json-schema.org/draft/2020-12/schema"
# never synced: the app's own sync fields
EXCLUDED_FIELDS = frozenset({"espresso_sync_ids", "exclude_from_sync"})
LAYOUT_FIELDTYPES = frozenset(display_fieldtypes) | {"Fold"}
INTEGER_FIELDTYPES = frozenset({"Int", "Long Int"})
NUMBER_FIELDTYPES = frozenset({"Float", "Currency", "Percent", "Rating", "Duration"})
# no type: any JSON value
ANY_FIELDTYPES = frozenset({"JSON"})
FORMATS = {"Date": "date", "Datetime": "date-time", "Time": "time"}
DATA_FORMATS = {"Email": "email", "URL": "uri"}
STANDARD_READ_FIELDS = {
	"name": ("Data", "ID"),
	"owner": ("Link", "Created By"),
	"creation": ("Datetime", "Created On"),
	"modified": ("Datetime", "Last Updated On"),
	"modified_by": ("Link", "Last Updated By"),
	"docstatus": ("Int", "Document Status"),
	"idx": ("Int", "Index"),
}
CHILD_READ_FIELDS = {
	"parent": ("Data", "Parent"),
	"parentfield": ("Data", "Parent Field"),
	"parenttype": ("Data", "Parent Type"),
}
MAX_DIAGNOSTICS = 200


def is_synced(df) -> bool:
	return (
		df.fieldtype not in LAYOUT_FIELDTYPES
		and not df.get("is_virtual")
		and df.fieldname not in EXCLUDED_FIELDS
		and df.fieldname not in default_fields
	)


def requiredness(df, meta, new_values: dict[str, Any], mode: str) -> str | None:
	""" "hard" when an insert must give the field, "server" when Frappe fills it in, else None.
	Only an insert has required fields."""
	if mode != "insert" or not df.reqd:
		return None
	if df.fieldtype in table_fields:
		return "hard"
	if df.get("default") not in (None, "") or df.get("fetch_from"):
		return "server"
	autoname = (meta.autoname or "").lower()
	if df.fieldname == "naming_series" and autoname.startswith("naming_series:"):
		return "server"
	if new_values.get(df.fieldname) not in (None, "", []):
		return "server"
	return "hard"


def max_length(df, meta) -> int | None:
	"""The length Frappe refuses to go beyond (a varchar column's)."""
	if meta.issingle:
		return None
	column = frappe.db.type_map.get(df.fieldtype)
	if not column or column[0] != "varchar":
		return None
	return frappe.utils.cint(df.get("length")) or frappe.utils.cint(column[1]) or None


def x_frappe(df, required: str | None) -> dict[str, Any]:
	fieldtype = df.fieldtype
	options = df.get("options") or None
	return {
		"fieldtype": fieldtype,
		"options": options,
		"link": options if fieldtype == "Link" else None,
		"dynamic_link": options if fieldtype == "Dynamic Link" else None,
		"required": required,
		"read_only": bool(df.get("read_only")),
		"custom": bool(df.get("is_custom_field")),
	}


def field_schema(df, meta, new_values: dict[str, Any], mode: str, seen: tuple[str, ...]) -> dict[str, Any]:
	fieldtype = df.fieldtype
	schema: dict[str, Any] = {}
	if fieldtype in table_fields:
		schema["type"] = "array"
	elif fieldtype == "Check":
		schema["type"] = ["integer", "boolean"]
		schema["enum"] = [0, 1, False, True]
	elif fieldtype in INTEGER_FIELDTYPES:
		schema["type"] = "integer"
	elif fieldtype in NUMBER_FIELDTYPES:
		schema["type"] = "number"
	elif fieldtype not in ANY_FIELDTYPES:
		schema["type"] = "string"
	if fieldtype in FORMATS:
		schema["format"] = FORMATS[fieldtype]
	elif fieldtype == "Data" and df.get("options") in DATA_FORMATS:
		schema["format"] = DATA_FORMATS[df.options]
	if fieldtype == "Select":
		options = [option.strip() for option in (df.get("options") or "").split("\n")]
		if any(options):
			schema["enum"] = list(dict.fromkeys(options))
	length = max_length(df, meta)
	if length and fieldtype != "Select":
		schema["maxLength"] = length
	if df.get("label"):
		schema["title"] = df.label
	if df.get("description"):
		schema["description"] = df.description
	if fieldtype in table_fields:
		# a row is a document of the child DocType; "$schema" belongs to the root only
		schema["items"] = {
			key: value
			for key, value in doctype_json_schema(df.options, mode, _seen=seen).items()
			if key != "$schema"
		}
	schema["x-frappe"] = x_frappe(df, requiredness(df, meta, new_values, mode))
	return schema


def standard_field_schema(fieldname: str, fieldtype: str, label: str, link: str | None = None) -> dict:
	schema: dict[str, Any] = {"type": "integer" if fieldtype == "Int" else "string", "title": label}
	if fieldtype == "Datetime":
		schema["format"] = "date-time"
	schema["x-frappe"] = {
		"fieldtype": fieldtype,
		"options": link,
		"link": link,
		"dynamic_link": None,
		"required": None,
		"read_only": True,
		"custom": False,
	}
	return schema


def new_values(meta) -> dict[str, Any]:
	"""What Frappe fills in on a new document: defaults, fetched values, the user."""
	try:
		return dict(cast(dict, frappe.new_doc(meta.name, as_dict=True)))
	except Exception:
		return {}


def doctype_json_schema(doctype: str, mode: str = "insert", *, _seen: tuple[str, ...] = ()) -> dict[str, Any]:
	"""The JSON Schema of `doctype`'s documents: as read ("read"), as given to insert a new
	one ("insert": its hard-required fields required) or to update one ("update": nothing
	required). Layout and virtual fields and the sync fields are left out."""
	if mode not in MODES:
		frappe.throw(_("{0} is not read, insert or update").format(mode))
	meta = frappe.get_meta(doctype)
	if doctype in _seen:
		frappe.throw(_("{0} contains itself").format(doctype))
	seen = (*_seen, doctype)
	values = new_values(meta) if mode == "insert" else {}
	# a document as Frappe gives it (as_dict, the REST API) and takes it (get_doc) names its
	# DocType: accepted, and only as this one
	properties: dict[str, Any] = {"doctype": standard_field_schema("doctype", "Data", "DocType")}
	properties["doctype"]["const"] = doctype
	if mode == "read":
		standard = {**STANDARD_READ_FIELDS, **(CHILD_READ_FIELDS if meta.istable else {})}
		for fieldname, (fieldtype, label) in standard.items():
			link = "User" if fieldname in ("owner", "modified_by") else None
			properties[fieldname] = standard_field_schema(fieldname, fieldtype, label, link)
	else:
		properties["name"] = standard_field_schema("name", "Data", "ID")
		properties["name"]["x-frappe"]["read_only"] = False
	required = []
	for df in meta.fields:
		if not is_synced(df):
			continue
		schema = field_schema(df, meta, values, mode, seen)
		properties[str(df.fieldname)] = schema
		if schema["x-frappe"]["required"] == "hard":
			required.append(df.fieldname)
	return {
		"$schema": JSON_SCHEMA,
		"type": "object",
		"title": doctype,
		"x-frappe": {"doctype": doctype, "mode": mode, "istable": bool(meta.istable)},
		"properties": properties,
		"required": required,
		"additionalProperties": False,
	}


# validation

format_checker = FormatChecker(formats=())


def parses(value) -> bool:
	"""Whether Frappe can read `value` as a date, a datetime or a time (it parses them with
	dateutil when they are not ISO; frappe.utils.getdate would also show the error)."""
	if not isinstance(value, str):
		return True
	try:
		date_parser.parse(value)
	except ValueError, OverflowError:
		return False
	return True


format_checker.checks("date")(parses)
format_checker.checks("date-time")(parses)
format_checker.checks("time")(parses)


@format_checker.checks("email")
def is_email(value) -> bool:
	return not isinstance(value, str) or bool(validate_email_address(value))


def is_numeric_string(value) -> bool:
	if not isinstance(value, str):
		return False
	try:
		float(value)
	except ValueError:
		return False
	return True


def entry(path, severity: str, code: str, message: str) -> dict[str, Any]:
	return {
		"rule": None,
		"path": pointer_of(path),
		"severity": severity,
		"code": code,
		"message": message,
		"origin": "doctype",
	}


def classify(error: ValidationError, mode: str) -> dict[str, Any] | None:
	"""An error of the schema as Frappe would take the value: an error where it refuses
	it, a warning where it converts or ignores it, nothing for an empty optional value."""
	keyword = error.validator
	field = error.schema.get("x-frappe") if isinstance(error.schema, dict) else None
	fieldtype = (field or {}).get("fieldtype")
	path = list(error.absolute_path)
	value = error.instance
	if keyword in ("type", "enum", "format", "maxLength") and value in (None, ""):
		if (field or {}).get("required") == "hard" and mode == "insert":
			return entry(path, "error", "required", _("A value is required"))
		return None
	if keyword in ("type", "enum") and fieldtype in INTEGER_FIELDTYPES | NUMBER_FIELDTYPES | {"Check"}:
		if is_numeric_string(value) or (isinstance(value, float) and fieldtype != "Check"):
			return entry(
				path,
				"warning",
				"numeric-string",
				_("{0} is converted to a number").format(frappe.as_json(value)),
			)
		if isinstance(value, int | float) and not isinstance(value, bool) and fieldtype == "Check":
			return entry(
				path, "warning", "check-number", _("{0} is stored as {1}").format(value, int(bool(value)))
			)
	if keyword == "additionalProperties":
		return entry(
			path,
			"warning",
			"unknown-field",
			_("Not a field of the DocType, and ignored: {0}").format(error.message),
		)
	if keyword == "required":
		missing = [name for name in error.validator_value if isinstance(value, dict) and name not in value]
		name = next((name for name in missing if repr(name) in error.message), None)
		return entry([*path, name] if name else path, "error", "required", _("A value is required"))
	return entry(path, "error", f"schema-{keyword}", error.message[:500])


def is_blank(value: Any, fieldtype: str | None, options: str | None) -> bool:
	"""Whether Frappe takes `value` of a mandatory field as missing: None, [], or text with
	nothing in it but spaces and HTML tags (an image counts in a Text Editor). As
	Document._get_missing_mandatory_fields has it, which needs a Document and is private."""
	if value is None or value == []:
		return True
	if fieldtype == "Check" or not isinstance(value, str):
		return False
	if "<img" in value and (fieldtype == "Text Editor" or (fieldtype == "Code" and options == "HTML")):
		return False
	return not strip_html(value).strip()


def blank_and_mandatory(
	field: dict[str, Any], doctype_meta, fieldname: str, value: Any, mode: str | None, in_row: bool
) -> bool:
	"""Whether a field given `value` is one Frappe refuses as missing: a hard-required one in
	an insert, a mandatory one in an update (where nothing is filled in, but for None on a
	new child row, which gets the field's default)."""
	meta = field.get("x-frappe") or {}
	if not is_blank(value, meta.get("fieldtype"), meta.get("options")):
		return False
	if mode == "insert":
		return meta.get("required") == "hard"
	if mode != "update" or doctype_meta is None:
		return False
	df = doctype_meta.get_field(fieldname)
	if not df or not df.reqd:
		return False
	return not (value is None and in_row and (df.get("default") not in (None, "") or df.get("fetch_from")))


def check_notes(schema: dict[str, Any], payload: Any, path: list) -> list[dict[str, Any]]:
	"""Errors on mandatory fields given an empty value, information on Check fields given
	as booleans, and warnings on required fields left for Frappe to fill in, through child
	rows too."""
	if not isinstance(payload, dict):
		return []
	notes = []
	properties = schema.get("properties") or {}
	mode = (schema.get("x-frappe") or {}).get("mode")
	doctype = (schema.get("x-frappe") or {}).get("doctype")
	doctype_meta = frappe.get_meta(doctype) if mode == "update" and doctype else None
	for fieldname, field in properties.items():
		meta = field.get("x-frappe") or {}
		value = payload.get(fieldname)
		if fieldname in payload and blank_and_mandatory(
			field, doctype_meta, fieldname, value, mode, in_row=bool(path)
		):
			notes.append(entry([*path, fieldname], "error", "required", _("A value is required")))
		if meta.get("fieldtype") == "Check" and isinstance(value, bool):
			notes.append(
				entry(
					[*path, fieldname],
					"info",
					"check-boolean",
					_("{0} is stored as {1}").format(frappe.as_json(value), int(value)),
				)
			)
		if mode == "insert" and meta.get("required") == "server" and value in (None, ""):
			notes.append(
				entry(
					[*path, fieldname],
					"warning",
					"server-filled",
					_("Required, and filled in by Frappe when not given"),
				)
			)
		if meta.get("fieldtype") in table_fields and isinstance(value, list):
			for index, row in enumerate(value):
				notes.extend(check_notes(field.get("items") or {}, row, [*path, fieldname, index]))
	return notes


def without_ignored_keys(schema: dict[str, Any], payload: Any) -> Any:
	"""`payload` without the keys Frappe marks a document's state with (__islocal,
	__unsaved...), on the document and its child rows, and without the app's own sync
	fields, which a document read from the site has and the schema leaves out."""
	if not isinstance(payload, dict):
		return payload
	document = {
		key: value
		for key, value in payload.items()
		if not str(key).startswith("__") and key not in EXCLUDED_FIELDS
	}
	for fieldname, field in (schema.get("properties") or {}).items():
		rows = document.get(fieldname)
		if (field.get("x-frappe") or {}).get("fieldtype") in table_fields and isinstance(rows, list):
			document[fieldname] = [without_ignored_keys(field.get("items") or {}, row) for row in rows]
	return document


def validate_doctype_payload(doctype: str, payload: Any, mode: str = "insert") -> list[dict[str, Any]]:
	"""Diagnostics ({rule, path, severity, code, message, origin}) for a document payload."""
	schema = doctype_json_schema(doctype, mode)
	payload = without_ignored_keys(schema, payload)
	validator = Draft202012Validator(schema, format_checker=format_checker)
	diagnostics: dict[tuple[str, str], dict[str, Any]] = {}
	for error in validator.iter_errors(payload):
		item = classify(error, mode)
		if item:
			# a Check given "1" fails its type and its enum: one diagnostic
			diagnostics.setdefault((item["path"], item["code"]), item)
		if len(diagnostics) >= MAX_DIAGNOSTICS:
			break
	for item in check_notes(schema, payload, []):
		diagnostics.setdefault((item["path"], item["code"]), item)
	return sorted(diagnostics.values(), key=lambda item: item["path"])
