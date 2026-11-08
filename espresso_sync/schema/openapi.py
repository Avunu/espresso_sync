# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""OpenAPI 3.1 descriptions: reading, validating, and the JSON Schema of an operation.

Only OpenAPI 3.1 is stored. The browser upgrades Swagger 2.0 and OpenAPI 3.0 and bundles
external references before it saves a spec, so a stored spec refers only to itself
("#/..."): nothing here ever reads a file or the network to resolve a reference.
"""

import json
import re
from collections.abc import Iterator
from typing import Any, cast
from urllib.parse import quote, unquote

import frappe
import yaml
from frappe import _
from frappe.utils import sha256_hash
from jsonschema import ValidationError
from jsonschema.validators import extend
from jsonschema_path.loaders import JsonschemaSafeLoader, SafeLoader
from openapi_schema_validator import OAS31Validator
from openapi_spec_validator import OpenAPIV31SpecValidator
from referencing import Registry
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT202012

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
PARTS = ("response", "requestBody")
# the largest spec text read or stored
MAX_SPEC_BYTES = 10 * 1024 * 1024
# the most nodes a spec may expand to (YAML aliases) and an operation schema to (references)
MAX_NODES = 1_000_000
MAX_SCHEMA_NODES = 200_000
MAX_DEPTH = 200
MAX_DIAGNOSTICS = 200
# where the spec sits in the registry payloads are validated with
SPEC_URI = "urn:espresso-sync:spec"
# a reference's siblings that only describe: laid over the referenced schema
ANNOTATIONS = frozenset(
	{
		"title",
		"description",
		"summary",
		"deprecated",
		"readOnly",
		"writeOnly",
		"example",
		"examples",
		"default",
		"$comment",
	}
)
# a schema's keywords whose values are data, not schemas: never expanded
DATA_KEYWORDS = frozenset({"example", "examples", "default", "const", "enum"})
# a schema's keywords whose values map names to schemas: their keys are names, never keywords
SCHEMA_MAPS = frozenset({"properties", "patternProperties", "$defs", "definitions", "dependentSchemas"})
BOOL_TAG = "tag:yaml.org,2002:bool"


class SpecError(Exception):
	"""A spec that cannot be read, is not OpenAPI 3.1, or is not valid."""

	def __init__(self, message: str, errors: list[str] | None = None):
		super().__init__(message)
		self.errors = errors or []


class SpecLoader(SafeLoader):
	"""openapi-spec-validator's YAML loader (JsonschemaSafeLoader: dates stay strings), but
	with YAML 1.2's booleans, only true and false, as JSON has them: a property or an enum
	value named on, off, yes or no stays one."""


SpecLoader.yaml_implicit_resolvers = {
	first: [(tag, regexp) for tag, regexp in resolvers if tag != BOOL_TAG]
	for first, resolvers in cast(type[SafeLoader], JsonschemaSafeLoader).yaml_implicit_resolvers.items()
}
SpecLoader.add_implicit_resolver(
	BOOL_TAG, re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF")
)


def json_key(key: Any) -> str:
	"""A mapping key as JSON has it: 200 → "200", true → "true", null → "null"."""
	if isinstance(key, str):
		return key
	return json.dumps(key) if isinstance(key, bool | None) else str(key)


def plain(value: Any, budget: list[int]) -> Any:
	"""`value` with string keys only, refusing more than `budget` nodes: YAML aliases can
	expand a short text into a huge tree, and no YAML loader bounds that."""
	budget[0] -= 1
	if budget[0] < 0:
		raise SpecError(_("The spec is too large"))
	if isinstance(value, dict):
		return {json_key(key): plain(item, budget) for key, item in value.items()}
	if isinstance(value, list | tuple):
		return [plain(item, budget) for item in value]
	return value


def load_spec_text(text: str | bytes) -> dict[str, Any]:
	"""Parse a spec from JSON or YAML text."""
	if isinstance(text, bytes):
		text = text.decode("utf-8-sig", errors="replace")
	if len(text.encode()) > MAX_SPEC_BYTES:
		raise SpecError(_("The spec is larger than {0} bytes").format(MAX_SPEC_BYTES))
	text = text.lstrip("﻿")
	try:
		value = json.loads(text)
	except ValueError:
		try:
			value = yaml.load(text, Loader=SpecLoader)
		except yaml.YAMLError as e:
			raise SpecError(_("The spec is neither JSON nor YAML: {0}").format(str(e))) from e
	value = plain(value, [MAX_NODES])
	if not isinstance(value, dict):
		raise SpecError(_("A spec is a JSON or YAML object"))
	return value


def spec_version(spec: dict[str, Any]) -> str:
	return str(spec.get("openapi") or spec.get("swagger") or "")


def spec_hash(spec: dict[str, Any]) -> str:
	"""sha256 of the spec's JSON, keys sorted: the same for the same spec, however written."""
	return sha256_hash(frappe.as_json(spec, indent=None))


# JSON Pointers and references


def escape(token: Any) -> str:
	return str(token).replace("~", "~0").replace("/", "~1")


def iter_refs(value: Any, pointer: str = "") -> Iterator[tuple[str, str]]:
	"""(pointer, reference) for each $ref and $dynamicRef in `value`, wherever it is: in an
	example or a default too, so that nothing a reader might follow is missed."""
	if isinstance(value, dict):
		for key, item in value.items():
			if key in ("$ref", "$dynamicRef") and isinstance(item, str):
				yield pointer, item
			else:
				yield from iter_refs(item, f"{pointer}/{escape(key)}")
	elif isinstance(value, list):
		for index, item in enumerate(value):
			yield from iter_refs(item, f"{pointer}/{index}")


def external_refs(spec: dict[str, Any]) -> list[str]:
	"""The references that leave the document: a stored spec is bundled and has none.
	(Checked here, as openapi-spec-validator would follow them.)"""
	return [f"{pointer}: {ref}" for pointer, ref in iter_refs(spec) if not ref.startswith("#")]


def refuse_retrieval(uri: str) -> Any:
	raise SpecError(
		_("{0} is outside the spec: a stored spec is never resolved against a file or a URL").format(uri)
	)


class RefuseAll(dict):
	"""Reference handlers with one for every scheme, which refuses. jsonschema_path falls
	back to requests.get or urlopen (file:// included) for a scheme it has no handler for,
	so an empty mapping would still read files and URLs."""

	def __missing__(self, scheme: str):
		return refuse_retrieval

	def __contains__(self, scheme: object) -> bool:
		return True


class SelfContainedSpecValidator(OpenAPIV31SpecValidator):
	"""The 3.1 validator whose references never leave the spec: it never opens a file or a
	URL."""

	resolver_handlers = RefuseAll()


def spec_errors(spec: Any) -> list[str]:
	"""Why `spec` cannot be stored, or [] when it can."""
	if not isinstance(spec, dict):
		return [_("A spec is a JSON object")]
	version = spec_version(spec)
	if not str(spec.get("openapi") or "").startswith("3.1."):
		return [
			_(
				"Only OpenAPI 3.1 is stored, and this is {0}: upgrade it on the import screen, which converts Swagger 2.0 and OpenAPI 3.0"
			).format(version or _("no OpenAPI version"))
		]
	external = external_refs(spec)
	if external:
		return [
			_("The spec refers outside itself (bundle it on the import screen): {0}").format(ref)
			for ref in external[:20]
		]
	errors = []
	try:
		for error in SelfContainedSpecValidator(spec).iter_errors():
			where = "/".join(str(part) for part in error.absolute_path)
			errors.append(f"{where or '/'}: {error.message}"[:500])
			if len(errors) >= 20:
				break
	except (Unresolvable, SpecError, LookupError, ValueError, RecursionError) as e:
		errors.append(_("The spec cannot be read: {0}").format(str(e)))
	return errors


def throw(e: SpecError):
	"""frappe.throw a SpecError, with its reasons."""
	messages = [str(e), *e.errors]
	frappe.throw(
		"<br>".join(frappe.utils.escape_html(message) for message in messages), title=_("Invalid API Spec")
	)


def validate_canonical(spec: Any) -> dict[str, Any]:
	"""Return `spec` when it is a valid, self-contained OpenAPI 3.1 description; raise
	SpecError with the reasons otherwise."""
	errors = spec_errors(spec)
	if errors:
		raise SpecError(_("The spec is not valid OpenAPI 3.1"), errors)
	return spec


def unescape(token: str) -> str:
	return token.replace("~1", "/").replace("~0", "~")


def pointer_of(tokens: list[Any] | tuple[Any, ...]) -> str:
	return "".join(f"/{escape(token)}" for token in tokens)


def tokens_of(pointer: str) -> list[str]:
	if not pointer:
		return []
	if not pointer.startswith("/"):
		raise SpecError(_("{0} is not a JSON Pointer").format(pointer))
	return [unescape(token) for token in pointer[1:].split("/")]


def spec_registry(spec: dict[str, Any]) -> Registry:
	"""A registry holding only the spec (at SPEC_URI): nothing else is ever retrieved."""
	return Registry().with_resource(SPEC_URI, DRAFT202012.create_resource(spec))


def ref_to(pointer: str, base: str = "") -> str:
	"""The reference to a JSON Pointer: a URI fragment, so percent-encoded."""
	return f"{base}#{quote(pointer, safe='/~')}"


def resolve_ref(spec: dict[str, Any], ref: str) -> Any:
	"""What an internal reference ("#/components/schemas/Order") points at."""
	if not ref.startswith("#"):
		raise SpecError(_("{0} refers outside the spec").format(ref))
	try:
		return spec_registry(spec).resolver(SPEC_URI).lookup(ref).contents
	except Unresolvable as e:
		raise SpecError(_("{0} is not in the spec").format(ref)) from e


def follow(spec: dict[str, Any], node: Any, pointer: str) -> tuple[Any, str]:
	"""A Reference Object followed to what it refers to, with where that is."""
	seen = set()
	while isinstance(node, dict) and isinstance(node.get("$ref"), str):
		ref = node["$ref"]
		if ref in seen:
			raise SpecError(_("{0} refers to itself").format(ref))
		seen.add(ref)
		node, pointer = resolve_ref(spec, ref), unquote(ref[1:])
	return node, pointer


# operations


def operation_parameters(spec: dict[str, Any], path_item: dict[str, Any], op: dict[str, Any]) -> list[dict]:
	"""The operation's parameters, the path's included, the operation's winning."""
	parameters: dict[tuple[str, str], dict] = {}
	for parameter in [*path_item.get("parameters", []), *op.get("parameters", [])]:
		parameter, _pointer = follow(spec, parameter, "")
		if isinstance(parameter, dict) and parameter.get("name"):
			parameters[(parameter["name"], parameter.get("in", ""))] = {
				"name": parameter["name"],
				"in": parameter.get("in"),
				"required": bool(parameter.get("required")),
				"description": parameter.get("description"),
				"schema": parameter.get("schema"),
			}
	return list(parameters.values())


def iter_operations(spec: dict[str, Any]) -> Iterator[tuple[str, str, dict[str, Any], dict[str, Any]]]:
	for path, path_item in (spec.get("paths") or {}).items():
		path_item, _pointer = follow(spec, path_item, "")
		if not isinstance(path_item, dict):
			continue
		for method in HTTP_METHODS:
			op = path_item.get(method)
			if isinstance(op, dict):
				yield method, path, path_item, op


def list_operations(spec: dict[str, Any]) -> list[dict[str, Any]]:
	"""One summary per operation: method, path, id, summary, tags, and what it sends and
	answers."""
	operations = []
	for method, path, path_item, op in iter_operations(spec):
		request_body, _pointer = follow(spec, op.get("requestBody"), "")
		operations.append(
			{
				"method": method.upper(),
				"path": path,
				"operation_id": op.get("operationId"),
				"summary": op.get("summary") or "",
				"tags": op.get("tags") or [],
				"deprecated": bool(op.get("deprecated")),
				"request_body": sorted((request_body or {}).get("content") or {})
				if isinstance(request_body, dict)
				else [],
				"responses": list((op.get("responses") or {}).keys()),
				"parameters": [
					{"name": p["name"], "in": p["in"], "required": p["required"]}
					for p in operation_parameters(spec, path_item, op)
				],
			}
		)
	return operations


def find_operation(spec: dict[str, Any], method: str, path: str) -> tuple[dict, dict, str]:
	"""(path item, operation, pointer of the operation)."""
	path_item, item_pointer = follow(spec, (spec.get("paths") or {}).get(path), pointer_of(["paths", path]))
	op = path_item.get(method.lower()) if isinstance(path_item, dict) else None
	if not isinstance(op, dict):
		raise SpecError(_("The spec has no {0} {1} operation").format(method.upper(), path))
	return path_item, op, f"{item_pointer}/{method.lower()}"


def pick_media_type(content: dict[str, Any]) -> str | None:
	"""JSON first: application/json, then any +json type, then */*, then the first."""
	types = list(content)
	for media_type in types:
		if media_type.split(";")[0].strip().lower() == "application/json":
			return media_type
	for media_type in types:
		if media_type.split(";")[0].strip().lower().endswith("+json"):
			return media_type
	for media_type in types:
		if media_type.strip() in ("*/*", "application/*"):
			return media_type
	return types[0] if types else None


def pick_status(responses: dict[str, Any]) -> str | None:
	"""The success response: the lowest 2XX, then 2XX, then default."""
	codes = sorted(code for code in responses if code.isdigit() and code.startswith("2"))
	if codes:
		return codes[0]
	for code in ("2XX", "2xx", "default"):
		if code in responses:
			return code
	return None


def operation_part(
	spec: dict[str, Any], method: str, path: str, part: str = "response", status: str | None = None
) -> dict[str, Any]:
	"""Where the schema of an operation's request body or response is: {pointer (None when
	it has no body), media_type, status}."""
	if part not in PARTS:
		raise SpecError(_("{0} is not response or requestBody").format(part))
	_path_item, op, op_pointer = find_operation(spec, method, path)
	if part == "requestBody":
		body, pointer = follow(spec, op.get("requestBody"), f"{op_pointer}/requestBody")
		status = None
	else:
		responses = op.get("responses") or {}
		status = str(status) if status else pick_status(responses)
		if status is None or status not in responses:
			raise SpecError(_("{0} {1} has no {2} response").format(method.upper(), path, status or "2XX"))
		body, pointer = follow(spec, responses[status], f"{op_pointer}/responses/{escape(status)}")
	content = (body.get("content") or {}) if isinstance(body, dict) else {}
	media_type = pick_media_type(content)
	if media_type is None or not isinstance(content[media_type], dict) or "schema" not in content[media_type]:
		return {"pointer": None, "media_type": media_type, "status": status}
	return {
		"pointer": f"{pointer}/content/{escape(media_type)}/schema",
		"media_type": media_type,
		"status": status,
	}


def dereference(
	spec: dict[str, Any],
	node: Any,
	stack: tuple[str, ...] = (),
	budget: list[int] | None = None,
	names: bool = False,
) -> Any:
	"""`node` with each internal reference replaced by what it refers to. A reference met
	again inside its own expansion becomes {"x-cycle": "<reference>"}: our own, as the
	dereferencing libraries (jsonref, prance) give a circular tree that is not JSON. `names` is true for
	a map of names to schemas (properties, $defs...), whose keys are names, not keywords: a
	property named "default" is a schema like any other."""
	budget = budget if budget is not None else [MAX_SCHEMA_NODES]
	budget[0] -= 1
	if budget[0] < 0 or len(stack) > MAX_DEPTH:
		raise SpecError(_("The schema is too large to expand"))
	if isinstance(node, list):
		return [dereference(spec, item, stack, budget) for item in node]
	if not isinstance(node, dict):
		return node
	if names:
		return {key: dereference(spec, value, stack, budget) for key, value in node.items()}
	ref = node.get("$ref")
	if isinstance(ref, str):
		if ref in stack:
			return {"x-cycle": ref}
		resolved = dereference(spec, resolve_ref(spec, ref), (*stack, ref), budget)
		siblings = {key: value for key, value in node.items() if key != "$ref"}
		if not siblings:
			return resolved
		siblings = dereference(spec, siblings, stack, budget)
		if isinstance(resolved, dict) and "x-cycle" not in resolved and set(siblings) <= ANNOTATIONS:
			return {**resolved, **siblings}
		return {**siblings, "allOf": [resolved, *siblings.get("allOf", [])]}
	return {
		key: value
		if key in DATA_KEYWORDS
		else dereference(spec, value, stack, budget, names=key in SCHEMA_MAPS)
		for key, value in node.items()
	}


def operation_schema(
	spec: dict[str, Any], method: str, path: str, part: str = "response", status: str | None = None
) -> dict[str, Any] | None:
	"""The JSON Schema of an operation's request body or response, references expanded
	(recursive ones marked with x-cycle), or None when it has no body."""
	where = operation_part(spec, method, path, part, status)
	if where["pointer"] is None:
		return None
	return dereference(spec, {"$ref": ref_to(where["pointer"])})


# data and schema locations


def schema_branches(schema: dict[str, Any], keyword_path: str) -> Iterator[tuple[dict[str, Any], str]]:
	"""`schema` and the subschemas of its allOf / anyOf / oneOf, with their paths."""
	yield schema, keyword_path
	for keyword in ("allOf", "anyOf", "oneOf"):
		for index, branch in enumerate(schema.get(keyword) or []):
			if isinstance(branch, dict):
				yield from schema_branches(branch, f"{keyword_path}/{keyword}/{index}")


def child_schema(schema: dict[str, Any], path: str, token: str) -> tuple[dict[str, Any], str] | None:
	"""The subschema a data token (a property name, or an index) goes to."""
	for branch, branch_path in schema_branches(schema, path):
		if token.isdigit() or token in ("-", "*"):
			for keyword in ("prefixItems",):
				items = branch.get(keyword)
				if isinstance(items, list) and token.isdigit() and int(token) < len(items):
					return items[int(token)], f"{branch_path}/{keyword}/{token}"
			if isinstance(branch.get("items"), dict):
				return branch["items"], f"{branch_path}/items"
		properties = branch.get("properties") or {}
		if token in properties and isinstance(properties[token], dict):
			return properties[token], f"{branch_path}/properties/{escape(token)}"
	for branch, branch_path in schema_branches(schema, path):
		for pattern, subschema in (branch.get("patternProperties") or {}).items():
			try:
				if re.search(pattern, token) and isinstance(subschema, dict):
					return subschema, f"{branch_path}/patternProperties/{escape(pattern)}"
			except re.error:
				continue
		if isinstance(branch.get("additionalProperties"), dict):
			return branch["additionalProperties"], f"{branch_path}/additionalProperties"
	return None


def data_ptr_to_schema_path(schema: dict[str, Any], data_ptr: str) -> str | None:
	"""The JSON Pointer, in an expanded schema, of the subschema that describes the value at
	`data_ptr` (no library maps a data location to a schema location). Array indexes may be left out ("/lines/qty" is "/lines/0/qty"), as a rule's
	pointer does. None when the schema does not describe it."""
	node, path = schema, ""
	for token in tokens_of(data_ptr):
		if not isinstance(node, dict):
			return None
		step = child_schema(node, path, token)
		if step is None and not token.isdigit():
			# an index left out: step into the items, then look again
			items = child_schema(node, path, "*")
			if items is not None:
				step = child_schema(items[0], items[1], token)
		if step is None:
			return None
		node, path = step
	return path


# payloads


# openapi-schema-validator checks readOnly and writeOnly for OpenAPI 3.0 only
def _read_only(validator, value, instance, schema):
	if value:
		yield ValidationError("is read-only: a request does not send it")


def _write_only(validator, value, instance, schema):
	if value:
		yield ValidationError("is write-only: a response does not carry it")


WriteValidator = extend(OAS31Validator, {"readOnly": _read_only})
ReadValidator = extend(OAS31Validator, {"writeOnly": _write_only})
# keywords whose failures are warnings: the value is sent, and the API may take it
WARNING_KEYWORDS = frozenset({"format", "readOnly", "writeOnly"})


def diagnostic(error: ValidationError, origin: str) -> dict[str, Any]:
	keyword = str(error.validator)
	path = list(error.absolute_path)
	if keyword == "required" and isinstance(error.instance, dict):
		# the path of the property that is missing, not of the object
		missing = [name for name in error.validator_value or [] if name not in error.instance]
		path += [name for name in missing if repr(name) in error.message][:1]
	return {
		"rule": None,
		"path": pointer_of(path),
		"severity": "warning" if keyword in WARNING_KEYWORDS else "error",
		"code": f"schema-{keyword}",
		"message": error.message[:500],
		"origin": origin,
	}


def validate_payload(
	spec: dict[str, Any], schema_pointer: str, payload: Any, write: bool = False
) -> list[dict]:
	"""Diagnostics for `payload` against the schema at `schema_pointer` in `spec` (in a
	request when `write`, where readOnly properties are flagged; in a response otherwise,
	where writeOnly ones are). References resolve inside the spec only."""
	registry = spec_registry(spec)
	validator_class = WriteValidator if write else ReadValidator
	validator = validator_class(
		{"$ref": ref_to(schema_pointer, SPEC_URI)},
		registry=registry,
		format_checker=OAS31Validator.FORMAT_CHECKER,
	)
	diagnostics = []
	try:
		for error in validator.iter_errors(payload):
			diagnostics.append(diagnostic(error, "openapi"))
			if len(diagnostics) >= MAX_DIAGNOSTICS:
				break
	except (Unresolvable, RecursionError) as e:
		diagnostics.append(
			{
				"rule": None,
				"path": "",
				"severity": "error",
				"code": "schema-unresolvable",
				"message": str(e)[:500],
				"origin": "openapi",
			}
		)
	return sorted(diagnostics, key=lambda item: item["path"])


# authentication


def auth_hints(spec: dict[str, Any]) -> list[dict[str, Any]]:
	"""What each of the spec's securitySchemes suggests for a Connection's authentication.
	A suggestion only: nothing applies it."""
	hints = []
	schemes = ((spec.get("components") or {}).get("securitySchemes")) or {}
	required = {name for requirement in spec.get("security") or [] for name in (requirement or {})}
	for name, scheme in schemes.items():
		scheme, _pointer = follow(spec, scheme, "")
		if not isinstance(scheme, dict):
			continue
		kind = scheme.get("type")
		http_scheme = str(scheme.get("scheme") or "").lower()
		suggestion = None
		if kind == "apiKey" and scheme.get("in") == "header" and scheme.get("name"):
			suggestion = {"auth_type": "Header-based", "api_key": scheme["name"]}
			note = _("Header-based, with {0} as the header and the key as the API Secret").format(
				scheme["name"]
			)
		elif kind == "http" and http_scheme == "basic":
			suggestion = {"auth_type": "Basic"}
			note = _("Basic, with the user as the API Key and the password as the API Secret")
		elif kind == "http" and http_scheme == "bearer":
			suggestion = {"auth_type": "Header-based", "api_key": "Authorization"}
			note = _("Header-based, with Authorization as the header and 'Bearer <token>' as the API Secret")
		else:
			where = f" in {scheme.get('in')}" if scheme.get("in") else ""
			note = _("{0}{1} is not supported: set the Connection's authentication by hand").format(
				kind or _("an unknown scheme"), where
			)
		hints.append(
			{
				"scheme": name,
				"type": kind,
				"in": scheme.get("in"),
				"name": scheme.get("name"),
				"http_scheme": http_scheme or None,
				"required": name in required,
				"suggestion": suggestion,
				"note": note,
			}
		)
	return hints
