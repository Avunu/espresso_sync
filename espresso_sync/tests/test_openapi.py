# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

import builtins
import copy
import json
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from frappe.tests import IntegrationTestCase
from jsonschema_path import retrievers
from referencing.exceptions import Unresolvable

from espresso_sync.schema import openapi
from espresso_sync.schema.openapi import SpecError

FIXTURES = Path(__file__).parent / "fixtures" / "openapi"


def fixture(name: str) -> dict:
	return openapi.load_spec_text((FIXTURES / name).read_text())


@contextmanager
def no_retrieval():
	"""Fail the test if anything opens a URL or a file to resolve a reference."""

	def refuse(*args, **kwargs):
		raise AssertionError(f"a reference was retrieved: {args}")

	with (
		patch.object(retrievers, "urlopen", refuse),
		patch.object(retrievers.requests, "get", refuse),
		patch.object(urllib.request, "urlopen", refuse),
	):
		yield


def schema_of(*args) -> dict:
	schema = openapi.operation_schema(*args)
	assert schema is not None
	return schema


class TestLoading(IntegrationTestCase):
	def test_yaml_dates_on_and_integer_keys(self):
		spec = fixture("yaml_quirks.yaml")
		# a YAML timestamp stays a string
		self.assertEqual(spec["info"]["version"], "2026-01-01")
		# an integer key is a string, as JSON has it
		responses = spec["paths"]["/switches"]["get"]["responses"]
		self.assertEqual(list(responses), ["200"])
		schema = responses["200"]["content"]["application/json"]["schema"]
		# YAML 1.2: on, off, yes and no are strings, as keys and as values
		self.assertEqual(list(schema["properties"]), ["on", "off", "state", "since", "count"])
		self.assertEqual(schema["properties"]["state"]["enum"], ["on", "off", "yes", "no"])
		self.assertEqual(schema["properties"]["since"]["example"], "2026-01-01")
		self.assertEqual(openapi.spec_errors(spec), [])
		# YAML 1.2 numbers: no sexagesimal, no leading-zero octal, no underscores
		numbers = openapi.load_spec_text(
			"a: [12:30, 0755, 1_000, 1e3, 0o17, 0x1F, +5, -3, .5, 1.5e-3, -.inf, 0b11, 1.2.3]\n"
		)["a"]
		self.assertEqual(numbers[:10], ["12:30", 755, "1_000", 1000.0, 15, 31, 5, -3, 0.5, 0.0015])
		self.assertIsInstance(numbers[3], float)
		self.assertEqual(numbers[10:], [float("-inf"), "0b11", "1.2.3"])
		with self.assertRaises(SpecError):
			openapi.load_spec_text("a: !!int 0b11\n")

	def test_other_keys_and_values(self):
		spec = openapi.load_spec_text("a: {true: 1, null: 2, 1.5: 3, 7: yes}\nb: [true, false, ~]\n")
		self.assertEqual(spec, {"a": {"true": 1, "null": 2, "1.5": 3, "7": "yes"}, "b": [True, False, None]})
		self.assertEqual(openapi.load_spec_text(b'\xef\xbb\xbf{"openapi": "3.1.0"}'), {"openapi": "3.1.0"})

	def test_what_is_not_a_spec(self):
		for text in ("[1, 2]", "just text", "a: [unclosed", '"string"'):
			with self.subTest(text=text), self.assertRaises(SpecError):
				openapi.load_spec_text(text)

	def test_an_alias_bomb_is_refused(self):
		lines = ['a0: &a0 ["x", "x", "x", "x", "x", "x", "x", "x", "x", "x"]']
		lines += [f"a{i}: &a{i} [{', '.join([f'*a{i - 1}'] * 10)}]" for i in range(1, 8)]
		with self.assertRaises(SpecError):
			openapi.load_spec_text("\n".join(lines))

	def test_the_size_cap(self):
		with patch.object(openapi, "MAX_SPEC_BYTES", 10), self.assertRaises(SpecError):
			openapi.load_spec_text('{"openapi": "3.1.0"}')

	def test_the_hash_ignores_key_order(self):
		spec = fixture("oas31.yaml")
		reordered = json.loads(json.dumps(dict(reversed(list(spec.items())))))
		self.assertEqual(openapi.spec_hash(spec), openapi.spec_hash(reordered))
		reordered["info"]["title"] = "Other"
		self.assertNotEqual(openapi.spec_hash(spec), openapi.spec_hash(reordered))


class TestValidation(IntegrationTestCase):
	def test_the_upgraded_fixtures_are_valid_31(self):
		for name in (
			"sw2_as_31.json",
			"oas30_as_31.yaml",
			"oas31.yaml",
			"recursive.yaml",
			"composition.yaml",
		):
			with self.subTest(name=name):
				self.assertEqual(openapi.spec_errors(fixture(name)), [])
				self.assertIs(openapi.validate_canonical(spec := fixture(name)), spec)

	def test_swagger_2_and_openapi_30_are_refused(self):
		for name, version in (("sw2.yaml", "2.0"), ("oas30.yaml", "3.0.3")):
			with self.subTest(name=name):
				errors = openapi.spec_errors(fixture(name))
				self.assertEqual(len(errors), 1)
				self.assertIn("Only OpenAPI 3.1", errors[0])
				self.assertIn(version, errors[0])
		self.assertEqual(openapi.spec_errors([]), ["A spec is a JSON object"])

	def test_an_invalid_spec_is_refused_with_reasons(self):
		spec = fixture("oas31.yaml")
		spec["paths"]["/orders"]["post"]["responses"] = "nope"
		with self.assertRaises(SpecError) as raised:
			openapi.validate_canonical(spec)
		self.assertTrue(raised.exception.errors)

	def test_a_file_reference_is_refused_and_never_read(self):
		spec = fixture("oas31.yaml")
		spec["components"]["schemas"]["Leak"] = {"$ref": "file:///etc/passwd"}
		spec["paths"]["/orders"]["post"]["requestBody"]["content"]["application/json"]["schema"] = {
			"$ref": "file:///etc/passwd#/x"
		}
		real_open = builtins.open

		def guarded_open(file, *args, **kwargs):
			if "passwd" in str(file):
				raise AssertionError("the spec's reference was read")
			return real_open(file, *args, **kwargs)

		with patch.object(builtins, "open", guarded_open), no_retrieval():
			errors = openapi.spec_errors(spec)
			self.assertTrue(errors)
			self.assertTrue(all("refers outside itself" in error for error in errors))
			# the validator itself refuses to read a reference, whatever its scheme
			with self.assertRaises(Unresolvable):
				list(openapi.SelfContainedSpecValidator(spec).iter_errors())
		# a $ref in data counts too: whatever a reader might follow is refused
		self.assertEqual(
			openapi.external_refs(
				{"examples": {"a": {"$ref": "http://x"}}, "x": {"$ref": "http://169.254.169.254/"}}
			),
			["/examples/a: http://x", "/x: http://169.254.169.254/"],
		)

	def test_a_reference_under_a_data_named_property_is_refused_and_never_followed(self):
		for name in ("default", "examples", "enum", "example", "const"):
			for ref in ("file:///etc/hostname", "http://169.254.169.254/latest/meta-data/iam"):
				spec = fixture("oas31.yaml")
				spec["components"]["schemas"]["Order"]["properties"][name] = {"$ref": ref}
				with self.subTest(name=name, ref=ref), no_retrieval():
					errors = openapi.spec_errors(spec)
					self.assertEqual(len(errors), 1)
					self.assertIn("refers outside itself", errors[0])
					self.assertIn(f"/properties/{name}: {ref}", errors[0])
					# and the validator, given it anyway, reads nothing either
					with self.assertRaises(Unresolvable):
						list(openapi.SelfContainedSpecValidator(spec).iter_errors())

	def test_a_base_uri_does_not_make_the_validator_read(self):
		# "#/..." is relative to $id: a schema that sets one points its references elsewhere
		spec = fixture("oas31.yaml")
		order = spec["components"]["schemas"]["Order"]
		order["$id"] = "file:///etc/hostname"
		order["properties"]["self"] = {"$ref": "#/x"}
		with no_retrieval():
			self.assertTrue(openapi.spec_errors(spec))
		self.assertTrue(isinstance(openapi.SelfContainedSpecValidator.resolver_handlers, dict))
		for scheme in ("file", "http", "https", "ftp", "", "urn"):
			self.assertIn(scheme, openapi.SelfContainedSpecValidator.resolver_handlers)
			with self.assertRaises(SpecError):
				openapi.SelfContainedSpecValidator.resolver_handlers[scheme](f"{scheme}:x")


class TestOperations(IntegrationTestCase):
	def test_list_operations(self):
		self.assertEqual(
			openapi.list_operations(fixture("composition.yaml")),
			[
				{
					"method": "POST",
					"path": "/payments",
					"operation_id": "createPayment",
					"summary": "Create a payment",
					"tags": ["payments"],
					"deprecated": False,
					"request_body": ["application/json"],
					"responses": ["201", "default"],
					"parameters": [],
				}
			],
		)
		operations = openapi.list_operations(fixture("oas30_as_31.yaml"))
		self.assertEqual(operations[0]["parameters"], [{"name": "id", "in": "path", "required": True}])

	def test_the_swagger_2_fixture(self):
		spec = fixture("sw2_as_31.json")
		schema = schema_of(spec, "post", "/orders", "requestBody")
		self.assertEqual(schema, openapi.operation_schema(spec, "POST", "/orders", "response", "201"))
		self.assertEqual(schema["required"], ["id", "lines"])
		self.assertEqual(schema["properties"]["lines"]["items"]["required"], ["sku"])
		self.assertEqual(schema["properties"]["note"]["type"], ["string", "null"])

	def test_the_openapi_30_fixture(self):
		spec = fixture("oas30_as_31.yaml")
		where = openapi.operation_part(spec, "get", "/orders/{id}")
		self.assertEqual(where["status"], "200")
		self.assertEqual(where["media_type"], "application/json")
		schema = schema_of(spec, "get", "/orders/{id}")
		line = schema["properties"]["lines"]["items"]
		self.assertEqual(
			line["allOf"][0],
			{"type": "object", "properties": {"line_id": {"type": "string", "format": "uuid"}}},
		)
		self.assertEqual(line["allOf"][1]["properties"]["qty"]["exclusiveMinimum"], 0)
		self.assertEqual(
			openapi.data_ptr_to_schema_path(schema, "/lines/0/line_id"),
			"/properties/lines/items/allOf/0/properties/line_id",
		)
		self.assertEqual(
			openapi.data_ptr_to_schema_path(schema, "/lines/qty"),
			"/properties/lines/items/allOf/1/properties/qty",
		)
		self.assertIsNone(openapi.data_ptr_to_schema_path(schema, "/lines/0/nope"))
		self.assertIsNone(openapi.data_ptr_to_schema_path(schema, "/id/x"))

	def test_recursive_references_get_cycle_markers(self):
		spec = fixture("recursive.yaml")
		schema = schema_of(spec, "get", "/categories/{id}")
		category = "#/components/schemas/Category"
		self.assertEqual(schema["properties"]["parent"], {"x-cycle": category})
		self.assertEqual(schema["properties"]["children"]["items"], {"x-cycle": category})
		owner = schema["properties"]["owner"]
		self.assertEqual(owner["properties"]["manager"], {"x-cycle": "#/components/schemas/Person"})
		self.assertEqual(
			openapi.data_ptr_to_schema_path(schema, "/owner/name"), "/properties/owner/properties/name"
		)
		# a payload validates against the spec itself, recursion included
		where = openapi.operation_part(spec, "get", "/categories/{id}")
		payload = {"name": "a", "children": [{"name": "b", "children": [{"children": []}]}]}
		diagnostics = openapi.validate_payload(spec, where["pointer"], payload)
		self.assertEqual(
			[(d["path"], d["code"]) for d in diagnostics],
			[("/children/0/children/0/name", "schema-required")],
		)

	def test_one_of_all_of_and_additional_properties(self):
		spec = fixture("composition.yaml")
		schema = schema_of(spec, "post", "/payments", "requestBody")
		self.assertEqual(len(schema["allOf"]), 2)
		body = schema["allOf"][1]["properties"]
		self.assertEqual(
			[branch["properties"]["kind"]["const"] for branch in body["method"]["oneOf"]], ["card", "bank"]
		)
		self.assertEqual(body["metadata"]["additionalProperties"], {"type": "string"})
		self.assertEqual(openapi.data_ptr_to_schema_path(schema, "/id"), "/allOf/0/properties/id")
		self.assertEqual(
			openapi.data_ptr_to_schema_path(schema, "/method/iban"),
			"/allOf/1/properties/method/oneOf/1/properties/iban",
		)
		self.assertEqual(
			openapi.data_ptr_to_schema_path(schema, "/metadata/anything"),
			"/allOf/1/properties/metadata/additionalProperties",
		)
		# the response, through a Response Object reference; and the error response
		self.assertEqual(openapi.operation_schema(spec, "post", "/payments", "response", "201"), schema)
		where = openapi.operation_part(spec, "post", "/payments", "response", "default")
		self.assertEqual(where["media_type"], "application/problem+json")

	def test_payload_validation(self):
		spec = fixture("composition.yaml")
		request = openapi.operation_part(spec, "post", "/payments", "requestBody")["pointer"]
		response = openapi.operation_part(spec, "post", "/payments", "response")["pointer"]
		good = {"amount": 5, "method": {"kind": "card", "last4": "4242"}, "metadata": {"order": "o1"}}
		self.assertEqual(openapi.validate_payload(spec, request, good, write=True), [])
		bad = {"id": "p1", "amount": "5", "method": {"kind": "card"}, "metadata": {"n": 1}, "created": "nope"}
		found = {
			(d["path"], d["code"], d["severity"])
			for d in openapi.validate_payload(spec, request, bad, write=True)
		}
		self.assertEqual(
			found,
			{
				("/id", "schema-readOnly", "warning"),
				("/created", "schema-readOnly", "warning"),
				("/created", "schema-format", "warning"),
				("/amount", "schema-type", "error"),
				("/method", "schema-oneOf", "error"),
				("/metadata/n", "schema-type", "error"),
			},
		)
		# in a response, readOnly is expected and writeOnly is not
		found = openapi.validate_payload(spec, response, {**good, "id": "p1", "secret": "s"})
		self.assertEqual([(d["path"], d["code"]) for d in found], [("/secret", "schema-writeOnly")])

	def test_an_unresolvable_reference_is_a_diagnostic(self):
		spec = copy.deepcopy(fixture("oas31.yaml"))
		spec["components"]["schemas"]["Order"] = {"$ref": "#/components/schemas/Missing"}
		where = openapi.operation_part(spec, "post", "/orders", "requestBody")
		diagnostics = openapi.validate_payload(spec, where["pointer"], {})
		self.assertEqual(diagnostics[0]["code"], "schema-unresolvable")
		with self.assertRaises(SpecError):
			openapi.operation_schema(spec, "post", "/orders", "requestBody")

	def test_missing_operations_and_parts(self):
		spec = fixture("oas31.yaml")
		for args in (
			("get", "/orders"),
			("post", "/nowhere"),
			("post", "/orders", "headers"),
			("post", "/orders", "response", "404"),
		):
			with self.subTest(args=args), self.assertRaises(SpecError):
				openapi.operation_part(spec, *args)
		# a response without a body
		self.assertIsNone(openapi.operation_schema(spec, "post", "/orders", "response"))

	def test_media_type_and_status_choice(self):
		self.assertEqual(
			openapi.pick_media_type({"text/plain": {}, "application/json; charset=utf-8": {}}),
			"application/json; charset=utf-8",
		)
		self.assertEqual(
			openapi.pick_media_type({"text/plain": {}, "application/hal+json": {}}), "application/hal+json"
		)
		self.assertEqual(openapi.pick_media_type({"text/plain": {}, "*/*": {}}), "*/*")
		self.assertEqual(openapi.pick_media_type({"text/plain": {}}), "text/plain")
		self.assertIsNone(openapi.pick_media_type({}))
		self.assertEqual(openapi.pick_status({"default": {}, "204": {}, "200": {}}), "200")
		self.assertEqual(openapi.pick_status({"default": {}, "2XX": {}}), "2XX")
		self.assertEqual(openapi.pick_status({"default": {}}), "default")
		self.assertIsNone(openapi.pick_status({"404": {}}))

	def test_a_reference_with_siblings(self):
		spec = {"components": {"schemas": {"A": {"type": "string"}}}}
		self.assertEqual(
			openapi.dereference(spec, {"$ref": "#/components/schemas/A", "description": "d"}),
			{"type": "string", "description": "d"},
		)
		self.assertEqual(
			openapi.dereference(spec, {"$ref": "#/components/schemas/A", "maxLength": 3}),
			{"maxLength": 3, "allOf": [{"type": "string"}]},
		)
		self.assertEqual(
			openapi.dereference(spec, {"enum": [{"$ref": "not followed"}], "examples": [{"$ref": "#/x"}]}),
			{"enum": [{"$ref": "not followed"}], "examples": [{"$ref": "#/x"}]},
		)

	def test_properties_named_like_data_keywords_are_expanded(self):
		spec = fixture("oas31.yaml")
		spec["components"]["schemas"]["Profile"] = {"type": "object", "properties": {"n": {"type": "string"}}}
		profile = {"$ref": "#/components/schemas/Profile"}
		order = spec["components"]["schemas"]["Order"]
		order["properties"].update(
			{
				"default": profile,
				"enum": profile,
				"examples": {"type": "array", "items": profile, "examples": [[profile]]},
				"const": {"type": "object", "$defs": {"example": profile}},
			}
		)
		order["patternProperties"] = {"^x-": profile}
		self.assertEqual(openapi.spec_errors(spec), [])
		schema = schema_of(spec, "post", "/orders", "requestBody")
		expanded = openapi.dereference(spec, profile)
		self.assertEqual(expanded["properties"], {"n": {"type": "string"}})
		properties = schema["properties"]
		self.assertEqual(properties["default"], expanded)
		self.assertEqual(properties["enum"], expanded)
		self.assertEqual(properties["examples"]["items"], expanded)
		# an example is data, and stays as written
		self.assertEqual(properties["examples"]["examples"], [[profile]])
		self.assertEqual(properties["const"]["$defs"]["example"], expanded)
		self.assertEqual(schema["patternProperties"]["^x-"], expanded)
		self.assertNotIn('"$ref"', json.dumps(properties["default"]))
		with self.assertRaises(SpecError):
			openapi.resolve_ref(spec, "other.yaml#/A")
		with self.assertRaises(SpecError):
			openapi.tokens_of("no-slash")
		with patch.object(openapi, "MAX_SCHEMA_NODES", 2), self.assertRaises(SpecError):
			openapi.dereference(spec, {"a": {"b": {"c": 1}}})


class TestAuthHints(IntegrationTestCase):
	def test_security_schemes_become_suggestions(self):
		hints = {hint["scheme"]: hint for hint in openapi.auth_hints(fixture("composition.yaml"))}
		self.assertEqual(hints["apiKey"]["suggestion"], {"auth_type": "Header-based", "api_key": "X-Api-Key"})
		self.assertTrue(hints["apiKey"]["required"])
		self.assertEqual(hints["basic"]["suggestion"], {"auth_type": "Basic"})
		self.assertEqual(
			hints["bearer"]["suggestion"], {"auth_type": "Header-based", "api_key": "Authorization"}
		)
		self.assertIsNone(hints["oauth"]["suggestion"])
		self.assertIn("not supported", hints["oauth"]["note"])
		self.assertEqual(openapi.auth_hints(fixture("oas31.yaml")), [])
