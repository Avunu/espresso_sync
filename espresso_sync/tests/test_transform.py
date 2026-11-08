# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import frappe
import responses
from frappe.desk.doctype.todo.todo import ToDo
from frappe.tests import IntegrationTestCase
from frappe.utils import background_jobs, safe_exec
from rq import Queue

from espresso_sync.api import schema as schema_api
from espresso_sync.api import transform as api
from espresso_sync.espresso_sync.doctype.espresso_sync_api_spec.espresso_sync_api_spec import (
	EspressoSyncAPISpec,
)
from espresso_sync.sync import ensure_sync_fields
from espresso_sync.tests.egress import public_dns
from espresso_sync.tests.test_schema_api import make_user
from espresso_sync.transform import dry_run, validate

FIXTURES = Path(__file__).parent / "fixtures"
CONNECTION = "ES Transform Test"
SERVER = "https://api.example.invalid/v1"
MANAGER_USER = "es-transform-manager@example.com"
WEBSITE_USER = "es-transform-website@example.com"


def make_connection() -> str:
	if not frappe.db.exists("Espresso Sync Connection", CONNECTION):
		frappe.get_doc(
			{
				"doctype": "Espresso Sync Connection",
				"connection_name": CONNECTION,
				"auth_type": "Header-based",
				"api_key": "X-Api-Key",
				"api_secret": "transform-secret",
				"server_url": SERVER,
				"sync_frequency": "Manual",
			}
		).insert(ignore_permissions=True)
	return CONNECTION


def make_spec() -> str:
	text = (FIXTURES / "openapi" / "tasks.yaml").read_text()
	spec_json = json.dumps(schema_api.openapi.load_spec_text(text))
	name = f"{CONNECTION} - Tasks"
	return schema_api.save_spec(
		spec_json,
		"Tasks",
		connection=make_connection(),
		name=name if frappe.db.exists(schema_api.SPEC, name) else None,
	)["name"]


TODO_RULES = [
	{"ptr": "/description", "kind": "field", "expr": "title"},
	{"ptr": "/status", "kind": "field", "expr": 'done ? "Closed" : "Open"'},
	{"ptr": "/date", "kind": "field", "expr": "$frappeDate(due)"},
	{"ptr": "/allocated_to", "kind": "field", "expr": "assignee"},
]
TASKS = [
	{"id": "t1", "title": "Grind beans", "done": False, "due": "2026-01-15", "assignee": "Administrator"},
	{"id": "t2", "title": "Descale", "done": True},
]


def make_transform(title: str, **values) -> Any:
	frappe.delete_doc("Espresso Sync Transform", title, force=True, ignore_missing=True)
	doc = frappe.get_doc(
		{
			"doctype": "Espresso Sync Transform",
			"title": title,
			"direction": "Import",
			"document_type": "ToDo",
			"api_spec": make_spec(),
			"method": "GET",
			"path": "/tasks",
			"items_pointer": "/data",
			"external_id_expr": "id",
			"rules": TODO_RULES,
			"sample": TASKS,
			**values,
		}
	)
	return doc.insert()


def codes(diagnostics) -> list[tuple]:
	return sorted((d["rule"], d["code"], d.get("item")) for d in diagnostics)


class TestTransform(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.enterContext(public_dns())
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def test_a_save_compiles_and_checks_the_rules(self):
		doc = make_transform(
			"ES Import Tasks",
			rules=[*TODO_RULES[1:], {"ptr": "/priority", "kind": "field", "expr": "priority ="}],
			external_id_expr="id ~>",
		)
		self.assertEqual(doc.status, "Draft")
		self.assertTrue(doc.compiled_jsonata.startswith('{\n\t"status": (done ? "Closed" : "Open"),'))
		self.assertEqual(
			codes(json.loads(doc.diagnostics)),
			[
				("/description", "required-unmapped", None),
				("/priority", "jsonata.S0207", None),
				("external_id_expr", "jsonata.S0207", None),
			],
		)
		self.assertTrue(doc.validated_source_hash and doc.validated_target_hash)
		self.assertTrue(all(d["origin"] == "server" for d in json.loads(doc.diagnostics)))

	def test_the_operation_must_be_in_the_spec(self):
		with self.assertRaises(frappe.ValidationError):
			make_transform("ES Import Nowhere", path="/nowhere")
		with self.assertRaises(frappe.ValidationError):
			make_transform("ES Import Child", document_type="Contact Email")

	def test_the_sample_is_mapped_and_checked(self):
		doc = make_transform(
			"ES Import Tasks",
			rules=[
				*TODO_RULES,
				{"ptr": "/priority", "kind": "field", "expr": "$uppercase(priority)"},
				{"ptr": "/reference_type", "kind": "field", "expr": '"Note"'},
				{"ptr": "/reference_name", "kind": "field", "expr": "id"},
			],
			sample=[
				{**TASKS[0], "priority": "high", "assignee": "nobody@example.invalid"},
				{"title": "Bad date", "due": "someday"},
			],
		)
		diagnostics = validate.validate_transform(doc)
		self.assertEqual(
			codes(diagnostics),
			[
				("", "eval.error", 1),
				("/allocated_to", "link-missing", 0),
				("/priority", "schema-enum", 0),
				("/reference_name", "link-missing", 0),
			],
		)
		# nothing was written
		self.assertEqual(json.loads(frappe.db.get_value(doc.doctype, doc.name, "diagnostics")), [])

	def test_activation_is_refused_on_errors(self):
		doc = make_transform("ES Import Tasks", rules=TODO_RULES[1:])
		with self.assertRaises(frappe.ValidationError) as raised:
			api.activate_transform(doc.name)
		self.assertIn("/description", str(raised.exception))
		doc.reload()
		self.assertEqual((doc.status, doc.active_compiled), ("Draft", None))

		# a runtime error in the sample is an error too
		doc.rules = json.dumps([*TODO_RULES, {"ptr": "/priority", "kind": "field", "expr": "$number(title)"}])
		doc.save()
		with self.assertRaises(frappe.ValidationError):
			api.activate_transform(doc.name)

	def test_activation_is_refused_when_the_schema_changed(self):
		doc = make_transform("ES Import Tasks")
		spec = cast(EspressoSyncAPISpec, frappe.get_doc(schema_api.SPEC, doc.api_spec))
		changed = json.loads(spec.spec_json)
		changed["components"]["schemas"]["Task"]["properties"]["done"]["type"] = "string"
		schema_api.save_spec(json.dumps(changed), spec.title, name=spec.name)
		with self.assertRaises(frappe.ValidationError) as raised:
			api.activate_transform(doc.name)
		self.assertIn("changed", str(raised.exception))
		# saved again, it is checked against the new schema
		doc.reload()
		doc.save()
		self.assertEqual(api.activate_transform(doc.name)["status"], "Active")

	def test_activation_freezes_the_rules(self):
		doc = make_transform("ES Import Tasks")
		result = api.activate_transform(doc.name)
		self.assertEqual(result["status"], "Active")
		self.assertEqual(result["active_compiled"], doc.compiled_jsonata)
		doc.reload()
		doc.rules = json.dumps(TODO_RULES[:1])
		doc.save()
		self.assertEqual(doc.status, "Active")
		self.assertEqual(doc.active_compiled, result["active_compiled"])
		self.assertNotEqual(doc.compiled_jsonata, doc.active_compiled)
		doc.rules = json.dumps(TODO_RULES)
		doc.save()
		ran = doc.active_hash()

		# anything else a sync reads makes it a Draft again, to be activated with the change
		for fieldname, value, before in (
			("path", "/tasks/{id}", "/tasks"),
			("runtime_validation", "Off", "Enforce"),
			("max_pages", 3, 10),
		):
			with self.subTest(fieldname):
				doc.set(fieldname, value)
				doc.save()
				self.assertEqual((doc.status, doc.active_compiled), ("Draft", None))
				doc.set(fieldname, before)
				doc.save()
				api.activate_transform(doc.name)
				doc.reload()
				self.assertEqual((doc.status, doc.active_hash()), ("Active", ran))

		# nor is a transform Active but through activation
		doc.reload()
		doc.status = "Active"
		doc.active_compiled = "{}"
		doc.save()
		self.assertEqual((doc.status, doc.active_compiled), ("Draft", None))

	def test_collections_and_dynamic_links(self):
		doc = make_transform(
			"ES Import People",
			document_type="Contact",
			path="/people",
			items_pointer="",
			rules=[
				{"ptr": "/first_name", "kind": "field", "expr": "name"},
				{"ptr": "/email_ids", "kind": "collection", "expr": "emails"},
				{"ptr": "/email_ids/email_id", "kind": "field", "expr": "$"},
				{"ptr": "/links", "kind": "collection", "expr": "user"},
				{"ptr": "/links/link_doctype", "kind": "field", "expr": '"User"'},
				{"ptr": "/links/link_name", "kind": "field", "expr": "$"},
				{"ptr": "/phone_nos", "kind": "collection", "expr": "phones"},
			],
			sample=[
				{"name": "Ada", "emails": ["ada@example.invalid"], "user": "Administrator"},
				{"name": "Bob", "emails": "bob@example.invalid", "user": "nobody@example.invalid"},
			],
		)
		self.assertEqual(
			codes(json.loads(doc.diagnostics)), [("/phone_nos/phone", "required-unmapped", None)]
		)
		self.assertEqual(
			codes(validate.validate_transform(doc)),
			[("/links/link_name", "link-missing", 1), ("/phone_nos/phone", "required-unmapped", None)],
		)
		results = dry_run.dry_run(doc)
		self.assertEqual(
			[r["output"]["email_ids"] for r in results][1], [{"email_id": "bob@example.invalid"}]
		)

	def test_an_export_maps_documents_to_the_request_body(self):
		todo = frappe.get_doc({"doctype": "ToDo", "description": "Export me", "status": "Closed"}).insert()
		doc = make_transform(
			"ES Export Tasks",
			direction="Export",
			method="POST",
			items_pointer=None,
			rules=[
				{"ptr": "/done", "kind": "field", "expr": 'status = "Closed"'},
				{"ptr": "/labels", "kind": "scalar_collection", "expr": "_user_tags"},
			],
			sample=None,
		)
		self.assertEqual(codes(json.loads(doc.diagnostics)), [("/title", "required-unmapped", None)])
		sample = api.fetch_sample(doc.name, limit=50)["items"]
		item = next(item for item in sample if item["name"] == todo.name)
		self.assertNotIn("espresso_sync_ids", item)
		doc.rules = json.dumps(
			[
				*json.loads(doc.rules),
				{"ptr": "/title", "kind": "field", "expr": "$substring(description, 0, 200)"},
			]
		)
		doc.sample = json.dumps([{**item, "description": "x" * 150}])
		doc.save()
		self.assertEqual(codes(api.validate_transform(doc.name)), [("/title", "schema-maxLength", 0)])
		results = api.dry_run(doc.name)
		self.assertEqual(results[0]["output"]["done"], True)
		self.assertIsNone(results[0]["name"])


class TestDryRun(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.enterContext(public_dns())
		frappe.set_user("Administrator")

	def test_nothing_is_left_behind(self):
		doc = make_transform("ES Import Tasks")
		before = frappe.db.count("ToDo")
		callbacks = len(frappe.db.after_commit._functions)

		def enqueue_jobs(todo=None):
			# every way a hook enqueues a job, the Server Script namespace's included
			frappe.enqueue("frappe.ping")
			background_jobs.enqueue("frappe.ping")
			safe_exec.safe_enqueue("frappe.ping")

		with patch.object(Queue, "enqueue_call") as enqueue:
			enqueue_jobs()
			self.assertEqual(enqueue.call_count, 3)
			enqueue.reset_mock()
			with patch.object(ToDo, "after_insert", enqueue_jobs, create=True):
				results = api.dry_run(doc.name)
		self.assertEqual([r["diagnostics"] for r in results], [[], []])
		self.assertTrue(all(r["name"] for r in results))
		self.assertEqual(results[0]["output"]["date"], "2026-01-15")
		self.assertEqual(frappe.db.count("ToDo"), before)
		self.assertFalse(frappe.db.exists("ToDo", {"description": "Grind beans"}))
		self.assertEqual(len(frappe.db.after_commit._functions), callbacks)
		enqueue.assert_not_called()

	def test_a_commit_in_a_hook_is_refused(self):
		doc = make_transform("ES Import Tasks")
		before = frappe.db.count("ToDo")

		def commit(todo):
			# a hook that commits: the dry run refuses it, which is what is tested
			frappe.db.commit()  # nosemgrep: frappe-nix-test-commit

		with patch.object(ToDo, "on_update", commit, create=True):
			results = api.dry_run(doc.name)
		self.assertEqual(
			[codes(r["diagnostics"]) for r in results],
			[[("", "dry-run.CommitRefused", 0)], [("", "dry-run.CommitRefused", 1)]],
		)
		self.assertEqual(frappe.db.count("ToDo"), before)
		with dry_run.nothing_kept(), self.assertRaises(dry_run.CommitRefused):
			# refused inside a dry run, which is what is tested
			frappe.db.commit()  # nosemgrep: frappe-nix-test-commit


class TestEndpoints(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.enterContext(public_dns())
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def test_for_system_managers_only(self):
		doc = make_transform("ES Import Tasks")
		frappe.set_user(make_user(WEBSITE_USER))
		for call in (
			lambda: api.validate_transform(doc.name),
			lambda: api.dry_run(doc.name),
			lambda: api.activate_transform(doc.name),
			lambda: api.resolve_functions([]),
			lambda: api.fetch_sample(doc.name),
		):
			with self.assertRaises(frappe.PermissionError):
				call()

	def test_resolve_functions(self):
		ensure_sync_fields("ToDo")
		doc = make_transform("ES Import Tasks")
		todo = frappe.get_doc(
			{
				"doctype": "ToDo",
				"description": "resolve me",
				"espresso_sync_ids": [{"sync_connection": CONNECTION, "external_id": "ext-7"}],
			}
		).insert()
		frappe.set_user(make_user(MANAGER_USER, ["System Manager"]))
		frappe.clear_messages()
		results = api.resolve_functions(
			json.dumps(
				[
					{"function": "syncId", "args": ["ToDo", todo.name]},
					{"function": "localName", "args": ["ToDo", "ext-7"]},
					{"function": "frappeCheck", "args": ["true"]},
					{"function": "getValue", "args": ["Server Script", "x", "script"]},
					{"function": "eval", "args": ["1"]},
					{"function": "frappeDate", "args": ["never"]},
				]
			),
			transform=doc.name,
		)
		self.assertEqual(results[:3], [{"value": "ext-7"}, {"value": todo.name}, {"value": 1}])
		self.assertEqual([r.get("code") for r in results[3:]], ["permission", "unknown-function", "error"])
		self.assertFalse(frappe.local.message_log)

	@responses.activate
	def test_fetch_sample_from_the_api(self):
		doc = make_transform(
			"ES Import Task",
			path="/tasks/{id}",
			items_pointer="",
			path_params='{"id": "a b/1"}',
			query_params='{"expand": "all"}',
		)
		responses.get(f"{SERVER}/tasks/a%20b%2F1?expand=all", json={"id": "a b/1", "title": "One"})
		self.assertEqual(
			api.fetch_sample(doc.name), {"items": [{"id": "a b/1", "title": "One"}], "more": False}
		)
		self.assertEqual(responses.calls[0].request.headers["X-Api-Key"], "transform-secret")

		doc = make_transform("ES Import Tasks")
		responses.get(f"{SERVER}/tasks", json={"data": [{"id": n} for n in range(5)]})
		self.assertEqual(
			api.fetch_sample(doc.name, start=1, limit=2), {"items": [{"id": 1}, {"id": 2}], "more": True}
		)
		doc.db_set("items_pointer", "/nowhere")
		with self.assertRaises(frappe.ValidationError):
			api.fetch_sample(doc.name)


class TestChecks(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.enterContext(public_dns())
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def test_required_fields_of_objects_and_collections(self):
		item = {"type": "object", "required": ["sku"], "properties": {"sku": {"type": "string"}}}
		schema = {
			"allOf": [
				{"required": ["id"], "properties": {"id": {"type": "string"}}},
				{
					"required": ["address"],
					"properties": {
						"address": {"type": "object", "required": ["city"], "properties": {"city": {}}},
						"lines": {"type": "array", "items": item},
					},
				},
			]
		}
		found = validate.required_diagnostics(
			schema, {"/address/street": "field", "/lines": "collection", "/id": "field"}
		)
		self.assertEqual(
			codes(found),
			[("/address/city", "required-unmapped", None), ("/lines/sku", "required-unmapped", None)],
		)
		self.assertEqual(
			codes(validate.required_diagnostics({"type": "array", "items": item}, {"": "collection"})),
			[("/sku", "required-unmapped", None)],
		)
		self.assertEqual(validate.required_diagnostics(schema, {"": "field"}), [])
		self.assertEqual(validate.object_parts(None), ({}, []))

	def test_child_table_keys_are_expressions(self):
		doc = make_transform(
			"ES Import People",
			document_type="Contact",
			path="/people",
			items_pointer="",
			rules=[{"ptr": "/first_name", "kind": "field", "expr": "name"}],
			child_table_policy="Merge by Key",
			child_table_keys=json.dumps({"email_ids": "email_id", "phone_nos": " ", "links": "link_name ="}),
		)
		self.assertEqual(
			codes(json.loads(doc.diagnostics)),
			[("child_table_keys", "compile.empty", None), ("child_table_keys", "jsonata.S0207", None)],
		)
		doc.child_table_policy = "Replace"
		self.assertEqual(doc.get_child_table_keys(), {})

	def test_links_to_unknown_or_unreadable_doctypes(self):
		doc = make_transform(
			"ES Import Tasks",
			rules=[
				*TODO_RULES,
				{"ptr": "/reference_type", "kind": "field", "expr": "kind"},
				{"ptr": "/reference_name", "kind": "field", "expr": "id"},
			],
			sample=[{**TASKS[1], "kind": "No Such DocType"}, {**TASKS[1], "kind": "Server Script"}],
		)
		frappe.set_user(make_user(MANAGER_USER, ["System Manager"]))
		found = [d for d in validate.validate_transform(doc) if d["code"].startswith("link-")]
		self.assertEqual(
			codes(found),
			[
				("/reference_name", "link-doctype", 0),
				("/reference_name", "link-unreadable", 1),
				("/reference_type", "link-missing", 0),
			],
		)

	def test_request_parameters(self):
		doc = make_transform("ES Import Task", path="/tasks/{id}", path_params='{"id": nothing}')
		with self.assertRaises(frappe.ValidationError):
			doc.request_url(SERVER, {}, CONNECTION)
		doc.path_params = '{"id": 7}'
		self.assertEqual(doc.request_url(f"{SERVER}/", {}, CONNECTION), (f"{SERVER}/tasks/7", {}))
		doc.query_params = '"page=1"'
		with self.assertRaises(frappe.ValidationError):
			doc.request_url(SERVER, {}, CONNECTION)

	@responses.activate
	def test_a_sample_that_cannot_be_fetched(self):
		doc = make_transform("ES Import Tasks")
		responses.get(f"{SERVER}/tasks", status=500)
		with self.assertRaises(frappe.ValidationError):
			api.fetch_sample(doc.name)
		responses.replace(responses.GET, f"{SERVER}/tasks", body="not json")
		with self.assertRaises(frappe.ValidationError):
			api.fetch_sample(doc.name)
		frappe.db.set_value("Espresso Sync Connection", CONNECTION, "server_url", None)
		with self.assertRaises(frappe.ValidationError):
			api.fetch_sample(doc.name)
		frappe.db.set_value(schema_api.SPEC, doc.api_spec, "connection", None)
		with self.assertRaises(frappe.ValidationError):
			api.fetch_sample(doc.name)
		with self.assertRaises(frappe.ValidationError):
			api.resolve_functions("[not json")
