# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""JSONata evaluation on the server (jsonata-python), and the functions an expression can
call besides JSONata's own.

Every evaluation is timeboxed: a runaway expression (an endless loop, a deep recursion)
raises D1012 or D1011 instead of holding the worker. The input goes through Frappe's JSON
encoder first, as jsonata-python reads only JSON types: datetimes, dates, Decimals and the
like become what an API would send, as strings or numbers.

The functions read the database as the session user, through frappe.get_list and
frappe.has_permission: an expression sees what its user may read, and nothing else.

- ``$syncId(doctype, name)``: the document's id in the Connection's API;
- ``$localName(doctype, id)``: the name of the document with that id in the Connection's API;
- ``$getValue(doctype, name, fieldname)``: a field of a document (of a Single: name it as
  its DocType). JSONata's own ``$single`` is not shadowed;
- ``$frappeDate(value)``, ``$frappeDatetime(value)``: a date or a datetime as Frappe
  stores it, converted to the system time zone when it has one;
- ``$frappeCheck(value)``: 0 or 1, from a boolean, a number or "true"/"false"/"1"/"0".
"""

import copy
import json
from collections.abc import Callable
from functools import lru_cache, partial
from typing import Any

import frappe
import jsonata
from frappe import _
from frappe.model import default_fields
from frappe.utils import convert_utc_to_system_timezone, get_date_str, get_datetime, get_datetime_str, sbool

TIMEOUT_MS = 5000
MAX_DEPTH = 200
SYNC_ID = "Espresso Sync ID"
SYNC_IDS_FIELD = "espresso_sync_ids"


@lru_cache(maxsize=512)
def compile_expression(expression: str) -> jsonata.Jsonata:
	"""Parse a JSONata expression once per process. A syntax error raises, and is not cached."""
	expr = jsonata.Jsonata(expression)
	# keep JSONata null (Utils.NULL_VALUE) apart from undefined (None)
	expr.set_output_convert_nulls(False)
	return expr


def as_json_value(value: Any) -> Any:
	"""`value` as JSON would carry it, through Frappe's encoder."""
	return json.loads(frappe.as_json(value, indent=None))


def as_text(value: Any) -> str:
	"""An id as text: a whole number without its ".0"."""
	if isinstance(value, float) and value.is_integer():
		value = int(value)
	return str(value)


def readable(doctype: str, name: Any) -> bool:
	"""Whether the session user may read the document (False when there is none)."""
	return bool(frappe.get_list(doctype, filters={"name": as_text(name)}, pluck="name", limit=1))


def sync_id(connection: str | None, doctype: str | None = None, name: Any = None) -> str | None:
	if not (connection and doctype and name is not None) or not readable(doctype, name):
		return None
	return frappe.db.get_value(
		SYNC_ID,
		{"parenttype": doctype, "parent": as_text(name), "sync_connection": connection},
		"external_id",
	)


def local_name(connection: str | None, doctype: str | None = None, external_id: Any = None) -> str | None:
	if not (connection and doctype and external_id is not None):
		return None
	if not frappe.get_meta(doctype).has_field(SYNC_IDS_FIELD):
		frappe.has_permission(doctype, "read", throw=True)
		return None
	names = frappe.get_list(
		doctype,
		filters=[
			[SYNC_ID, "sync_connection", "=", connection],
			[SYNC_ID, "external_id", "=", as_text(external_id)],
		],
		pluck="name",
		limit=1,
	)
	return names[0] if names else None


def get_value(doctype: str | None = None, name: Any = None, fieldname: str | None = None) -> Any:
	if not (doctype and name is not None and fieldname):
		return None
	meta = frappe.get_meta(doctype)
	if not meta.has_field(fieldname) and fieldname not in default_fields:
		frappe.throw(_("{0} has no field {1}").format(doctype, fieldname))
	if meta.issingle:
		frappe.has_permission(doctype, "read", throw=True)
		return as_json_value(frappe.db.get_single_value(doctype, fieldname))
	rows = frappe.get_list(doctype, filters={"name": as_text(name)}, fields=[fieldname], limit=1)
	return as_json_value(rows[0][fieldname]) if rows else None


def system_datetime(value: Any):
	try:
		moment = get_datetime(str(value))
	except ValueError:
		moment = None
	if moment is None:
		raise frappe.ValidationError(_("{0} is not a date").format(value))
	if moment.tzinfo is not None:
		moment = convert_utc_to_system_timezone(moment).replace(tzinfo=None)
	return moment


def frappe_date(value: Any = None) -> str | None:
	return None if value in (None, "") else get_date_str(system_datetime(value))


def frappe_datetime(value: Any = None) -> str | None:
	return None if value in (None, "") else get_datetime_str(system_datetime(value))


def frappe_check(value: Any = None) -> int | None:
	if value is None:
		return None
	return int(bool(sbool(value.strip()) if isinstance(value, str) else value))


def functions(connection: str | None = None) -> dict[str, Callable[..., Any]]:
	"""The functions an expression can call besides JSONata's own, by name (without the "$")."""
	return {
		"syncId": partial(sync_id, connection),
		"localName": partial(local_name, connection),
		"getValue": get_value,
		"frappeDate": frappe_date,
		"frappeDatetime": frappe_datetime,
		"frappeCheck": frappe_check,
	}


def evaluate(expression: str, data: Any, *, default: Any = None, connection: str | None = None) -> Any:
	"""The result of a JSONata expression on `data`: None for JSONata null, `default` when
	it is undefined. A syntax error, a runtime error and the timebox raise."""
	# jsonata-python evaluates on the thread's current instance (Jsonata.CURRENT), which
	# only its constructor sets, and $now() and $millis() read that instance's timestamp.
	# A cached expression is not constructed again, so a copy of it is made current: the
	# time is this evaluation's, and the cached instance is not changed by it.
	expr = copy.copy(compile_expression(expression))
	jsonata.Jsonata.CURRENT.jsonata = expr
	# a fresh frame per evaluation: its timebox starts now, not when the expression was
	# cached, and the functions it binds are this evaluation's (its Connection's)
	bindings = jsonata.Jsonata.Frame(None)
	bindings.set_runtime_bounds(TIMEOUT_MS, MAX_DEPTH)
	for name, function in functions(connection).items():
		bindings.bind(name, jsonata.Jsonata.JLambda(function))
	result = expr.evaluate(as_json_value(data), bindings)
	if result is None:
		return default
	return jsonata.Utils.convert_nulls(result)
