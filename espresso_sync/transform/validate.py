# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""What is wrong with a Transform, as diagnostics the editor shows on its rows.

Every diagnostic has the editor's shape (diagnostics.ts): {rule, path, severity, code,
message, origin, item?}. `rule` is the pointer of the rule it is about (of the field, for
a required one no rule fills), or the name of the Transform field holding the
expression; `path` is where in the mapped object, array indexes included; `item` is the
sample item that produced it; `origin` is "server".

The checks, from the cheapest:

1. the rules compile, and each expression parses (on every save);
2. every required field of the target is filled by a rule: the DocType's hard-required
   fields (doctype_schema's tiers), the request body's required properties; an import has
   an External ID;
3. each sample item maps, and what it maps to passes the target's schema: the DocType's,
   with Frappe's coercions as warnings and the fields Frappe fills in as warnings, or the
   operation's request body (openapi.validate_payload);
4. the Links and Dynamic Links it maps to exist, looked up in a batch per DocType as the
   session user: a document the user may not read counts as missing.

The dry run (dry_run.py) is the last check: the documents are saved, then rolled back.
"""

from contextlib import contextmanager
from typing import Any

import frappe
import jsonata
from frappe import _
from frappe.model import table_fields
from frappe.utils import strip_html

from espresso_sync.schema import openapi
from espresso_sync.schema.doctype_schema import doctype_json_schema, validate_doctype_payload
from espresso_sync.transform import engine
from espresso_sync.transform.compile import Compiled, compile_rules, rule_at

SPEC = "Espresso Sync API Spec"
# the Transform fields that hold a JSONata expression
EXPRESSION_FIELDS = ("path_params", "query_params", "next_request_expr", "external_id_expr", "modified_expr")
MAX_SAMPLE_ITEMS = 50


def diagnostic(
	rule: str, path: str, severity: str, code: str, message: str, item: int | None = None
) -> dict[str, Any]:
	entry: dict[str, Any] = {
		"rule": rule,
		"path": path,
		"severity": severity,
		"code": code,
		"message": message,
		"origin": "server",
	}
	if item is not None:
		entry["item"] = item
	return entry


@contextmanager
def without_messages():
	"""Drop the messages the block queues for the response (frappe.throw's): the
	diagnostics carry them."""
	count = len(frappe.local.message_log)
	try:
		yield
	finally:
		del frappe.local.message_log[count:]


def error_message(e: Exception) -> str:
	return strip_html(str(e)) or type(e).__name__


def parse_error(expression: str) -> tuple[str, str] | None:
	"""(code, message) when the expression does not parse."""
	try:
		engine.compile_expression(expression)
	except jsonata.JException as e:
		return f"jsonata.{e.error}", str(e)
	except Exception as e:
		return "jsonata.error", str(e)
	return None


class Sides:
	"""The two ends of a Transform: the API Spec operation's body (the response read by an
	import, the request body an export sends) and the DocType's documents (as inserted by
	an import, as read by an export)."""

	def __init__(self, transform):
		self.transform = transform
		self.importing = transform.direction == "Import"
		spec_doc = frappe.get_doc(SPEC, transform.api_spec)
		spec_doc.check_permission("read")
		self.connection: str | None = spec_doc.get("connection")
		part = "response" if self.importing else "requestBody"
		status = transform.response_status if self.importing else None
		try:
			self.spec = openapi.load_spec_text(spec_doc.get("spec_json") or "")
			where = openapi.operation_part(self.spec, transform.method, transform.path, part, status)
			self.operation = openapi.operation_schema(
				self.spec, transform.method, transform.path, part, where["status"]
			)
		except openapi.SpecError as e:
			openapi.throw(e)
			raise
		self.pointer: str | None = where["pointer"]
		self.doctype = doctype_json_schema(transform.document_type, "insert" if self.importing else "read")

	@property
	def source(self) -> dict[str, Any] | None:
		return self.operation if self.importing else self.doctype

	@property
	def target(self) -> dict[str, Any] | None:
		return self.doctype if self.importing else self.operation

	def hashes(self) -> tuple[str, str]:
		return openapi.spec_hash(self.source or {}), openapi.spec_hash(self.target or {})

	def target_diagnostics(self, output: Any) -> list[dict[str, Any]]:
		"""The target schema's findings on a mapped object."""
		if self.importing:
			return validate_doctype_payload(self.transform.document_type, output, "insert")
		if self.pointer is None:
			return []
		return openapi.validate_payload(self.spec, self.pointer, output, write=True)


def rule_kinds(rules: list[Any]) -> dict[str, str]:
	"""{pointer: kind} of the rules that compile."""
	return {
		rule["ptr"]: rule["kind"]
		for rule in rules
		if isinstance(rule, dict) and isinstance(rule.get("ptr"), str) and isinstance(rule.get("kind"), str)
	}


def nearest_rule(pointer: str, kinds: dict[str, str]) -> str:
	"""The nearest pointer at or above `pointer` that has a rule; `pointer` itself when none
	does (as diagnostics.ts's nearestRule)."""
	current = pointer
	while current not in kinds:
		if not current:
			return pointer
		current = current.rsplit("/", 1)[0]
	return current


def rule_pointer(path: str, data: Any) -> str:
	"""A data path with array indexes (/items/0/qty) as a rule pointer (/items/qty): a token
	is an index where the data has an array."""
	tokens = []
	for token in openapi.tokens_of(path):
		if isinstance(data, list):
			data = data[int(token)] if token.isdigit() and int(token) < len(data) else None
			continue
		tokens.append(token)
		data = data.get(token) if isinstance(data, dict) else None
	return openapi.pointer_of(tokens)


def object_parts(schema: Any) -> tuple[dict[str, Any], list[str]]:
	"""The properties and required names of an object schema, its allOf members' included."""
	if not isinstance(schema, dict):
		return {}, []
	properties = dict(schema.get("properties") or {})
	required = list(schema.get("required") or [])
	for member in schema.get("allOf") or []:
		member_properties, member_required = object_parts(member)
		properties.update(member_properties)
		required.extend(member_required)
	return properties, required


def required_diagnostics(schema: Any, kinds: dict[str, str]) -> list[dict[str, Any]]:
	"""An error for each required field no rule fills: at the root, in the objects the rules
	fill field by field, and in the items of the collections."""
	found = []

	def mapped(pointer: str) -> bool:
		return pointer in kinds or any(other.startswith(f"{pointer}/") for other in kinds)

	def walk(node: Any, pointer: str):
		properties, required = object_parts(node)
		for name in dict.fromkeys(required):
			child = f"{pointer}/{openapi.escape(name)}"
			if not mapped(child):
				found.append(
					diagnostic(
						child, child, "error", "required-unmapped", _("Required, and no rule fills it")
					)
				)
		for name, child_schema in properties.items():
			child = f"{pointer}/{openapi.escape(name)}"
			kind = kinds.get(child)
			if kind == "collection":
				walk((child_schema or {}).get("items"), child)
			elif kind is None and mapped(child):
				walk(child_schema, child)

	root_kind = kinds.get("")
	if root_kind == "collection":
		walk((schema or {}).get("items"), "")
	elif root_kind is None:
		walk(schema, "")
	return found


def static_diagnostics(transform, sides: Sides, compiled: Compiled) -> list[dict[str, Any]]:
	"""What the rules and expressions show without running them: compile errors, syntax
	errors, required fields no rule fills."""
	rules = transform.get_rules()
	found = [diagnostic(e.rule, e.rule, "error", e.code, e.message) for e in compiled.errors]
	for rule in rules:
		expression = rule.get("expr") if isinstance(rule, dict) else None
		if isinstance(expression, str) and expression.strip() and (error := parse_error(expression)):
			found.append(diagnostic(rule["ptr"], rule["ptr"], "error", *error))
	for fieldname in EXPRESSION_FIELDS:
		expression = transform.get(fieldname)
		if expression and (error := parse_error(expression)):
			found.append(diagnostic(fieldname, "", "error", *error))
	if sides.importing and not (transform.external_id_expr or "").strip():
		found.append(
			diagnostic(
				"external_id_expr",
				"",
				"error",
				"required",
				_("An import needs an External ID: without one, each sync imports every item again"),
			)
		)
	for table, expression in transform.get_child_table_keys().items():
		if not isinstance(expression, str) or not expression.strip():
			found.append(
				diagnostic(
					"child_table_keys", f"/{table}", "error", "compile.empty", _("An expression is required")
				)
			)
		elif error := parse_error(expression):
			found.append(diagnostic("child_table_keys", f"/{table}", "error", *error))
	found.extend(required_diagnostics(sides.target, rule_kinds(rules)))
	return found


def evaluation_diagnostic(e: Exception, compiled: Compiled, item: int) -> dict[str, Any]:
	if isinstance(e, jsonata.JException):
		rule = rule_at(compiled, e.location)
		return diagnostic(rule, rule, "error", f"eval.{e.error}", str(e), item)
	code = "eval.permission" if isinstance(e, frappe.PermissionError) else "eval.error"
	return diagnostic("", "", "error", code, error_message(e), item)


def map_item(sides: Sides, compiled: Compiled, kinds: dict[str, str], item: Any, index: int):
	"""(the mapped object, or None when it fails, and the diagnostics on it)."""
	try:
		with without_messages():
			output = engine.evaluate(compiled.jsonata, item, connection=sides.connection)
	except Exception as e:
		return None, [evaluation_diagnostic(e, compiled, index)]
	found = []
	for entry in sides.target_diagnostics(output):
		rule = nearest_rule(rule_pointer(entry["path"], output), kinds)
		found.append(
			diagnostic(rule, entry["path"], entry["severity"], entry["code"], entry["message"], index)
		)
	return output, found


def collect_links(doctype: str, doc: dict[str, Any], path: list, item: int, links: dict):
	"""Add each Link and Dynamic Link value of `doc` (and of its child rows) to `links`:
	{DocType: {name: [(item, path)]}}."""
	for df in frappe.get_meta(doctype).fields:
		value = doc.get(df.fieldname)
		if value in (None, "", []):
			continue
		if df.fieldtype in table_fields and isinstance(value, list) and df.options:
			for index, row in enumerate(value):
				if isinstance(row, dict):
					collect_links(df.options, row, [*path, df.fieldname, index], item, links)
			continue
		if df.fieldtype == "Link":
			target = df.options
		elif df.fieldtype == "Dynamic Link":
			target = doc.get(df.options)
		else:
			continue
		if isinstance(target, str) and target and isinstance(value, str | int | float):
			names = links.setdefault(target, {})
			names.setdefault(engine.as_text(value), []).append(
				(item, openapi.pointer_of([*path, df.fieldname]))
			)


def link_diagnostics(doctype: str, outputs: list[Any], kinds: dict[str, str]) -> list[dict[str, Any]]:
	"""An error for each Link or Dynamic Link to a document that does not exist or that
	the session user may not read, looked up in one query per DocType."""
	links: dict[str, dict[str, list]] = {}
	for item, output in enumerate(outputs):
		if isinstance(output, dict):
			collect_links(doctype, output, [], item, links)
	found = []
	for target, names in links.items():
		if not frappe.db.exists("DocType", target):
			missing = dict.fromkeys(names, ("link-doctype", _("{0} is not a DocType").format(target)))
		elif not frappe.has_permission(target, "read"):
			missing = dict.fromkeys(names, ("link-unreadable", _("Not permitted to read {0}").format(target)))
		else:
			existing = frappe.get_list(
				target, filters={"name": ["in", list(names)]}, pluck="name", limit=len(names)
			)
			known = {str(name).casefold() for name in existing}
			missing = {
				name: (
					"link-missing",
					_("{0} {1} does not exist, or you may not read it").format(target, name),
				)
				for name in names
				if name.casefold() not in known
			}
		for name, (code, message) in missing.items():
			for item, path in names[name]:
				rule = nearest_rule(rule_pointer(path, outputs[item]), kinds)
				found.append(diagnostic(rule, path, "error", code, message, item))
	return found


def validate_transform(transform, sides: Sides | None = None) -> list[dict[str, Any]]:
	"""Every check but the dry run, on the Transform as it is (saved or not). Writes nothing."""
	sides = sides or Sides(transform)
	compiled = compile_rules(transform.get_rules())
	found = static_diagnostics(transform, sides, compiled)
	kinds = rule_kinds(transform.get_rules())
	outputs = []
	for index, item in enumerate(transform.get_sample()[:MAX_SAMPLE_ITEMS]):
		output, item_diagnostics = map_item(sides, compiled, kinds, item, index)
		outputs.append(output)
		found.extend(item_diagnostics)
	if sides.importing:
		found.extend(link_diagnostics(transform.document_type, outputs, kinds))
	return found
