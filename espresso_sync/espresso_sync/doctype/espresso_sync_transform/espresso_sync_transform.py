# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

import hashlib
import json
import re
from typing import Any
from urllib.parse import quote

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import escape_html

from espresso_sync.schema import openapi
from espresso_sync.transform import engine, validate
from espresso_sync.transform.compile import compile_rules

PATH_PARAMETER = re.compile(r"\{([^{}]+)\}")
# what a sync reads besides the Active JSONata: changing one makes an Active transform a
# Draft again, to be checked and activated with it
RUN_FIELDS = (
	"document_type",
	"api_spec",
	"method",
	"path",
	"items_pointer",
	"path_params",
	"query_params",
	"next_request_expr",
	"max_pages",
	"external_id_expr",
	"modified_expr",
	"runtime_validation",
	"child_table_policy",
	"child_table_keys",
)
# the errors an activation refusal lists
SHOWN_ERRORS = 10


def json_value(value: Any) -> Any:
	return json.loads(value) if isinstance(value, str) and value.strip() else value


class EspressoSyncTransform(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		active_compiled: DF.Code | None
		api_spec: DF.Link
		child_table_keys: DF.JSON | None
		child_table_policy: DF.Literal["Replace", "Merge by Key"]
		compiled_jsonata: DF.Code | None
		diagnostics: DF.JSON | None
		direction: DF.Literal["Import", "Export"]
		document_type: DF.Link
		external_id_expr: DF.Code | None
		items_pointer: DF.Data | None
		max_pages: DF.Int
		method: DF.Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
		modified_expr: DF.Code | None
		next_request_expr: DF.Code | None
		path: DF.Data
		path_params: DF.Code | None
		query_params: DF.Code | None
		rules: DF.JSON | None
		runtime_validation: DF.Literal["Enforce", "Warn", "Off"]
		sample: DF.JSON | None
		status: DF.Literal["Draft", "Active"]
		title: DF.Data
		validated_source_hash: DF.Data | None
		validated_target_hash: DF.Data | None
	# end: auto-generated types

	def validate(self):
		# a share must not let anyone else change what a sync writes or sends
		if not self.flags.ignore_permissions:
			frappe.only_for("System Manager")
		# Frappe stores a JSON field's object as JSON, and refuses a list
		for fieldname in ("rules", "sample"):
			if isinstance(self.get(fieldname), list):
				self.set(fieldname, json.dumps(self.get(fieldname), ensure_ascii=False))
		# only activate() makes a transform Active, and what it activated stays as it was
		if (
			self.status == "Active"
			and not self.flags.activating
			and any(self.has_value_changed(f) for f in (*RUN_FIELDS, "status", "active_compiled"))
		):
			self.status = "Draft"
			self.active_compiled = None
			frappe.msgprint(_("{0} is a Draft again: activate it to run it").format(self.name), alert=True)
		if not (self.document_type and self.api_spec and self.path):
			# the mandatory check says what is missing
			return
		meta = frappe.get_meta(self.document_type)
		if meta.istable or meta.issingle:
			frappe.throw(
				_("{0} is a child table or a Single: choose another DocType").format(self.document_type)
			)
		sides = validate.Sides(self)
		compiled = compile_rules(self.get_rules())
		self.compiled_jsonata = compiled.jsonata
		self.diagnostics = json.dumps(validate.static_diagnostics(self, sides, compiled), ensure_ascii=False)
		self.validated_source_hash, self.validated_target_hash = sides.hashes()

	def get_rules(self) -> list[Any]:
		rules = json_value(self.rules)
		return rules if isinstance(rules, list) else []

	def get_sample(self) -> list[Any]:
		"""The sample's items: a list, or one item."""
		sample = json_value(self.sample)
		if sample is None:
			return []
		return sample if isinstance(sample, list) else [sample]

	def get_child_table_keys(self) -> dict[str, Any]:
		if self.direction != "Import" or self.child_table_policy != "Merge by Key":
			return {}
		keys = json_value(self.child_table_keys)
		return keys if isinstance(keys, dict) else {}

	def activate(self):
		"""Freeze the compiled rules as what runs, and make the transform Active. Refused
		while a check finds an error (a required field no rule fills is one), and when the
		API Spec's operation or the DocType changed since the transform was last saved."""
		sides = validate.Sides(self)
		if (self.validated_source_hash, self.validated_target_hash) != sides.hashes():
			frappe.throw(
				_(
					"The API Spec's operation or the DocType changed since this transform was saved: check it and save it again"
				),
				title=_("Not Activated"),
			)
		errors = [d for d in validate.validate_transform(self, sides) if d["severity"] == "error"]
		if errors:
			shown = "".join(
				f"<li>{escape_html(d['rule'] or d['path'] or '/')}: {escape_html(d['message'])}</li>"
				for d in errors[:SHOWN_ERRORS]
			)
			frappe.throw(
				_("{0} errors to fix first:").format(len(errors)) + f"<ul>{shown}</ul>",
				title=_("Not Activated"),
			)
		self.status = "Active"
		self.active_compiled = self.compiled_jsonata
		self.flags.activating = True
		try:
			self.save()
		finally:
			self.flags.activating = False

	def active_hash(self) -> str:
		"""SHA-256 of what a sync runs: the Active JSONata and the fields it reads."""
		ran = [self.active_compiled, *(self.get(fieldname) for fieldname in RUN_FIELDS)]
		return hashlib.sha256(frappe.as_json(ran, indent=None).encode()).hexdigest()

	def evaluate_object(self, fieldname: str, data: Any, connection: str | None) -> dict[str, Any]:
		"""The object an expression field gives on `data` ({} when it is empty or undefined)."""
		expression = self.get(fieldname)
		if not expression:
			return {}
		value = engine.evaluate(expression, data, default={}, connection=connection)
		if not isinstance(value, dict):
			frappe.throw(_("{0} must give an object").format(_(self.meta.get_label(fieldname))))
		return value

	def request_url(self, server_url: str, data: Any, connection: str | None) -> tuple[str, dict[str, Any]]:
		"""The operation's URL on the server, its path parameters filled in from Path
		Parameters, and the query parameters, both evaluated on `data`."""
		parameters = self.evaluate_object("path_params", data, connection)

		def fill(match: re.Match) -> str:
			value = parameters.get(match.group(1))
			if value in (None, ""):
				frappe.throw(_("Path Parameters gives no {0}").format(match.group(1)))
			return quote(engine.as_text(value), safe="")

		path = PATH_PARAMETER.sub(fill, self.path)
		return server_url.rstrip("/") + path, self.evaluate_object("query_params", data, connection)

	def read_items(self, body: Any) -> list[Any]:
		"""The items at the Items Pointer in a response body: a list there, or the one item."""
		try:
			for token in openapi.tokens_of(self.items_pointer or ""):
				body = body[int(token)] if isinstance(body, list) else body[token]
		except KeyError, IndexError, TypeError, ValueError, openapi.SpecError:
			frappe.throw(_("The response has nothing at {0}").format(self.items_pointer), title=_("No Items"))
		if body is None:
			return []
		return body if isinstance(body, list) else [body]
