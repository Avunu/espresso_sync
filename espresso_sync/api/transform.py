# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""The transform editor's endpoints: validate, dry-run and activate a Transform, resolve
the functions its expressions call, and fetch sample items. Each is for System Managers
only."""

import json
from typing import Any, cast

import frappe
import requests
from frappe import _
from frappe.utils import get_datetime

from espresso_sync.transform import dry_run as dry_run_module
from espresso_sync.transform import engine, validate
from espresso_sync.utils.safe_fetch import safe_request

TRANSFORM = "Espresso Sync Transform"
CONNECTION = "Espresso Sync Connection"
MAX_CALLS = 500
MAX_SAMPLE = 50


def get_transform(name: str, ptype: str = "read") -> Any:
	doc = frappe.get_doc(TRANSFORM, name)
	doc.check_permission(ptype)
	return doc


def json_argument(value: Any) -> Any:
	if isinstance(value, str):
		try:
			return json.loads(value)
		except ValueError:
			frappe.throw(_("Not JSON: {0}").format(value[:100]))
	return value


@frappe.whitelist()
def validate_transform(name: str) -> list[dict[str, Any]]:
	"""Every check of the Transform but the dry run, as diagnostics. Writes nothing."""
	frappe.only_for("System Manager")
	return validate.validate_transform(get_transform(name))


@frappe.whitelist(methods=["POST"])
def dry_run(name: str) -> list[dict[str, Any]]:
	"""The Transform run on its sample, nothing kept: for each item, what it maps to, the
	name an import's document gets, and what went wrong."""
	frappe.only_for("System Manager")
	return dry_run_module.dry_run(get_transform(name, "write"))


@frappe.whitelist(methods=["POST"])
def activate_transform(name: str, modified: str) -> dict[str, Any]:
	"""Make the Transform Active, its rules frozen as they are; refused while a check finds
	an error, when the schemas changed since it was saved, and, as a save is, when it was
	saved since `modified`, the version the caller read."""
	frappe.only_for("System Manager")
	doc = get_transform(name, "write")
	if get_datetime(modified) != get_datetime(doc.modified):
		frappe.throw(
			_(
				"{0} has been modified after you have opened it. Please refresh to get the latest document."
			).format(doc.name),
			frappe.TimestampMismatchError,
		)
	doc.activate()
	return {
		"name": doc.name,
		"status": doc.status,
		"active_compiled": doc.active_compiled,
		"modified": doc.modified,
	}


def connection_of(transform: str | None) -> str | None:
	if not transform:
		return None
	return frappe.db.get_value(validate.SPEC, get_transform(transform).api_spec, "connection")


@frappe.whitelist(methods=["POST"])
def resolve_functions(calls: str | list, transform: str | None = None) -> list[dict[str, Any]]:
	"""The results of calls to the app's JSONata functions ([{function: "getValue", args:
	[...]}], the function named without "$"), each {value} or {error, code}, as the
	session user. $syncId and $localName read the ids of `transform`'s Connection."""
	frappe.only_for("System Manager")
	calls = json_argument(calls)
	if not isinstance(calls, list) or len(calls) > MAX_CALLS:
		frappe.throw(_("Give a list of at most {0} calls").format(MAX_CALLS))
	functions = engine.functions(connection_of(transform))
	results = []
	for call in cast(list, calls):
		function = functions.get(call.get("function")) if isinstance(call, dict) else None
		args = call.get("args") if isinstance(call, dict) else None
		if function is None or not isinstance(args, list | None):
			results.append({"error": _("Not a function call"), "code": "unknown-function"})
			continue
		try:
			with validate.without_messages():
				results.append({"value": function(*(args or []))})
		except frappe.PermissionError as e:
			results.append({"error": validate.error_message(e), "code": "permission"})
		except Exception as e:
			results.append({"error": validate.error_message(e), "code": "error"})
	return results


def fetch_api_sample(doc) -> list[Any]:
	"""The items of the operation's response, from the Connection's server, with its
	credentials (sent only to its Allowed Host)."""
	connection_name = connection_of(doc.name)
	if not connection_name:
		frappe.throw(_("The API Spec has no Connection to fetch from"), title=_("No Sample"))
	connection = frappe.get_doc(CONNECTION, cast(str, connection_name))
	# the request carries the Connection's credentials
	connection.check_permission("write")
	server_url = connection.get("server_url")
	if not server_url:
		frappe.throw(_("Set the Connection's Server URL first"), title=_("No Sample"))
	url, query = doc.request_url(server_url, {}, connection_name)
	try:
		response = safe_request(
			doc.method,
			url,
			params=query,
			headers={"Accept": "application/json"},
			credentials=cast(Any, connection).get_credential_headers(),
			allowed_host=connection.get("allowed_host"),
		)
	except requests.RequestException as e:
		frappe.throw(_("{0} could not be fetched: {1}").format(url, str(e)), title=_("No Sample"))
		raise
	if not 200 <= response.status_code < 300:
		frappe.throw(_("{0} answered HTTP {1}").format(url, response.status_code), title=_("No Sample"))
	try:
		body = response.json()
	except ValueError:
		frappe.throw(_("{0} did not answer JSON").format(url), title=_("No Sample"))
	return doc.read_items(body)


def fetch_document_sample(doc, start: int, limit: int) -> list[Any]:
	"""Documents of the DocType as an export reads them, newest first, as the session user
	may read them."""
	names = frappe.get_list(
		doc.document_type, pluck="name", order_by="modified desc", offset=start, limit=limit
	)
	items = []
	for name in names:
		document = frappe.get_doc(doc.document_type, name)
		document.check_permission("read")
		items.append(engine.document_item(document))
	return items


@frappe.whitelist(methods=["POST"])
def fetch_sample(name: str, start: int = 0, limit: int = 20) -> dict[str, Any]:
	"""Sample items for the Transform, `limit` of them from `start`, and whether there are
	more: an import's from the operation's response (after the Items Pointer), an export's
	from the DocType. Nothing is stored: the editor saves the sample it keeps."""
	frappe.only_for("System Manager")
	doc = get_transform(name, "write")
	start, limit = max(start, 0), min(max(limit, 1), MAX_SAMPLE)
	if doc.direction == "Import":
		items = fetch_api_sample(doc)[start:]
	else:
		items = fetch_document_sample(doc, start, limit + 1)
	return {"items": items[:limit], "more": len(items) > limit}
