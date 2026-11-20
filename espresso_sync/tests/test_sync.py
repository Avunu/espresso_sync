# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""Syncs through Active transforms, against the tasks.yaml API mocked with responses."""

import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import frappe
import responses
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, now_datetime
from responses import matchers

from espresso_sync import scheduler, sync
from espresso_sync.api import schema as schema_api
from espresso_sync.espresso_sync.doctype.espresso_sync_connection import espresso_sync_connection as esc
from espresso_sync.tests.egress import public_dns
from espresso_sync.utils import safe_fetch

FIXTURES = Path(__file__).parent / "fixtures"
SERVER = "https://api.example.invalid/v1"
OTHER = "https://other.example.invalid"
SECRET = "sync-test-secret"
TRANSFORM = "Espresso Sync Transform"

IMPORT_TASKS: dict[str, Any] = {
	"direction": "Import",
	"document_type": "ToDo",
	"method": "GET",
	"path": "/tasks",
	"items_pointer": "/data",
	"query_params": '{"page": 1}',
	"next_request_expr": '$count(body.data) > 0 ? {"page": query.page + 1}',
	"external_id_expr": "id",
	"modified_expr": "updated",
	"rules": [
		{"ptr": "/description", "kind": "field", "expr": "title"},
		{"ptr": "/status", "kind": "field", "expr": 'done ? "Closed" : "Open"'},
		{"ptr": "/priority", "kind": "field", "expr": "priority"},
	],
}
EXPORT_TASKS: dict[str, Any] = {
	"direction": "Export",
	"document_type": "ToDo",
	"method": "POST",
	"path": "/tasks",
	"external_id_expr": "id",
	"rules": [
		{"ptr": "/title", "kind": "field", "expr": "description"},
		{"ptr": "/done", "kind": "field", "expr": 'status = "Closed"'},
	],
}
UPDATE_TASKS: dict[str, Any] = {
	**EXPORT_TASKS,
	"method": "PUT",
	"path": "/tasks/{id}",
	"path_params": '{"id": $syncId("ToDo", name)}',
}
# a link between two ToDos, made with a request of its own: the document's parent (its
# reference) gets the id of the ToDo just sent, from the answer to that request
FOLLOW_UP_TASKS: dict[str, Any] = {
	"direction": "Export",
	"document_type": "ToDo",
	"method": "POST",
	"path": "/tasks/{id}/links",
	"path_params": '{"id": $syncId("ToDo", reference_name)}',
	"skip_expr": "reference_name ? false : true",
	"rules": [{"ptr": "/task", "kind": "field", "expr": "$response.n"}],
}


def make_connection(name: str, **values) -> str:
	"""A new Connection, with nothing of an earlier one of the name left: no Pull Log, no
	Sync IDs (a create commits them)."""
	if frappe.db.exists("Espresso Sync Connection", name):
		frappe.delete_doc("Espresso Sync Connection", name, force=True)
	frappe.db.delete("Espresso Sync Pull Log", {"sync_connection": name})
	frappe.db.delete("Espresso Sync ID", {"sync_connection": name})
	frappe.get_doc(
		{
			"doctype": "Espresso Sync Connection",
			"connection_name": name,
			"auth_type": "Header-based",
			"api_key": "X-Api-Key",
			"api_secret": SECRET,
			"server_url": SERVER,
			"sync_frequency": "Manual",
			**values,
		}
	).insert(ignore_permissions=True)
	return name


def make_spec(connection: str) -> str:
	spec = schema_api.openapi.load_spec_text((FIXTURES / "openapi" / "tasks.yaml").read_text())
	name = f"{connection} - Tasks"
	return schema_api.save_spec(
		json.dumps(spec),
		"Tasks",
		connection=connection,
		name=name if frappe.db.exists(schema_api.SPEC, name) else None,
	)["name"]


def make_transform(title: str, spec: str, activate: bool = True, **values) -> str:
	frappe.delete_doc(TRANSFORM, title, force=True, ignore_missing=True)
	doc = cast(
		Any, frappe.get_doc({"doctype": TRANSFORM, "title": title, "api_spec": spec, **values}).insert()
	)
	if activate:
		doc.activate()
	return str(doc.name)


def add_shot(connection: str, **shot):
	doc = esc.get_connection(connection)
	doc.append("shots", shot)
	doc.save()


def pull_logs(connection: str) -> list:
	return frappe.get_all(
		"Espresso Sync Pull Log",
		filters={"sync_connection": connection},
		fields=[
			"sync_doc",
			"sync_status",
			"sync_direction",
			"request_type",
			"url",
			"response",
			"object",
			"diagnostics",
			"transform",
			"transform_hash",
		],
		order_by="creation asc, name asc",
	)


def codes(log) -> list[str]:
	return [d["code"] for d in json.loads(log.diagnostics or "[]")]


def task(external_id: str, title: str, updated: str = "2026-01-15T09:00:00Z", **values) -> dict:
	return {"id": external_id, "title": title, "done": False, "updated": updated, **values}


class SyncTestCase(IntegrationTestCase):
	"""Each test has its own Connection: a create commits, so what it leaves outlives it."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for doctype in ("ToDo", "Contact"):
			sync.ensure_sync_fields(doctype)

	def setUp(self):
		super().setUp()
		self.enterContext(public_dns())
		frappe.set_user("Administrator")
		self.connection = make_connection(f"ES Sync {self._testMethodName}")
		self.spec = make_spec(self.connection)
		# only what the test changes is exported: the site's other ToDos are older
		self.since = now_datetime()

	def transform(self, kind: str, values: dict, **changes) -> str:
		return make_transform(f"{self.connection} {kind}", self.spec, **{**values, **changes})

	def start_exports_now(self):
		"""An export reads only what changed since the test began."""
		connection = esc.get_connection(self.connection)
		connection.db_set("last_pull", add_to_date(self.since, days=1), update_modified=False)
		for shot in connection.shots:
			frappe.db.set_value(sync.SHOT, shot.name, "last_export", self.since, update_modified=False)

	def sync(self, *replies) -> list:
		"""Sync the Connection against `replies` ((method, url, kwargs) each); the calls made."""
		with responses.RequestsMock() as rsps:
			for method, url, kwargs in replies:
				rsps.add(method, url, **kwargs)
			esc.get_connection(self.connection).sync()
			calls = list(rsps.calls)
		return calls

	def todo(self, external_id: str) -> Any:
		names = frappe.get_all(
			"Espresso Sync ID",
			filters={"sync_connection": self.connection, "external_id": external_id, "parenttype": "ToDo"},
			pluck="parent",
		)
		self.assertEqual(len(names), 1, names)
		return frappe.get_doc("ToDo", names[0])


def page(number: int, *items: dict):
	return (
		responses.GET,
		f"{SERVER}/tasks",
		{"match": [matchers.query_param_matcher({"page": str(number)})], "json": {"data": list(items)}},
	)


class TestImport(SyncTestCase):
	def setUp(self):
		super().setUp()
		self.import_transform = self.transform("import", IMPORT_TASKS)
		add_shot(self.connection, dt="ToDo", do_import=1, import_transform=self.import_transform)

	def test_a_paginated_import_creates_then_updates(self):
		self.sync(
			page(1, task("p1", "es page one"), task("p2", "es page one, second")),
			page(2, task("p3", "es page two")),
			page(3),
		)
		first = self.todo("p1")
		self.assertEqual((first.description, first.status), ("es page one", "Open"))
		self.assertEqual(self.todo("p3").description, "es page two")

		logs = pull_logs(self.connection)
		# a request entry per page, holding its response, and an entry per item
		self.assertEqual([bool(log.response) for log in logs], [True, False, False, True, False, True])
		self.assertEqual([json.loads(log.object or "{}").get("id") for log in logs][1:3], ["p1", "p2"])
		self.assertEqual({log.sync_status for log in logs}, {"Success"})
		self.assertTrue(logs[0].url.endswith("/tasks?page=1"))
		ran = cast(Any, frappe.get_doc(TRANSFORM, self.import_transform)).active_hash()
		self.assertEqual(
			{(log.transform, log.transform_hash) for log in logs}, {(self.import_transform, ran)}
		)
		shot = esc.get_connection(self.connection).shots[0]
		self.assertIsNotNone(shot.last_import)

		# p1 changed in the API, p2 did not: p2 is skipped, and nothing is logged for it
		count = len(logs)
		self.sync(
			page(
				1,
				task("p1", "es page one, renamed", "2026-01-16T09:00:00Z", done=True),
				task("p2", "es page one, second, renamed"),
			),
			page(2),
		)
		updated = self.todo("p1")
		self.assertEqual(updated.name, first.name)
		self.assertEqual((updated.description, updated.status), ("es page one, renamed", "Closed"))
		self.assertEqual(self.todo("p2").description, "es page one, second")
		self.assertEqual(len(pull_logs(self.connection)), count + 3)
		self.assertEqual(frappe.db.count("ToDo", {"description": ("like", "es page one%")}), 2)

	def test_the_query_reads_the_last_import(self):
		frappe.db.set_value(TRANSFORM, self.import_transform, "next_request_expr", None)
		frappe.db.set_value(
			TRANSFORM, self.import_transform, "query_params", '{"page": 1, "since": last_import}'
		)
		shot = esc.get_connection(self.connection).shots[0]
		frappe.db.set_value(sync.SHOT, shot.name, "last_import", "2026-01-15 09:00:00", update_modified=False)
		calls = self.sync(
			(
				responses.GET,
				f"{SERVER}/tasks",
				{
					"match": [matchers.query_param_matcher({"page": "1", "since": "2026-01-15 09:00:00"})],
					"json": {"data": []},
				},
			)
		)
		self.assertEqual(len(calls), 1)

	def test_enforce_blocks_an_invalid_object_and_logs_it(self):
		frappe.db.set_value(TRANSFORM, self.import_transform, "next_request_expr", None)
		self.sync(page(1, task("e1", "es invalid", priority="urgent"), task("e2", "es valid")))
		self.assertFalse(
			frappe.get_all("Espresso Sync ID", {"external_id": "e1", "sync_connection": self.connection})
		)
		self.assertEqual(self.todo("e2").description, "es valid")
		[_request, invalid, valid] = pull_logs(self.connection)
		self.assertEqual(invalid.sync_status, "Failure")
		self.assertEqual(codes(invalid)[-1], "invalid-payload")
		self.assertIn("schema-enum", codes(invalid))
		# Warn: saved, and here Frappe refuses it too, which leaves nothing behind
		frappe.db.set_value(TRANSFORM, self.import_transform, "runtime_validation", "Warn")
		todos = frappe.db.count("ToDo")
		self.sync(page(1, task("e1", "es invalid", priority="urgent")))
		failed = pull_logs(self.connection)[-1]
		self.assertEqual((failed.sync_status, codes(failed)[-1]), ("Failure", "ValidationError"))
		self.assertIn("schema-enum", codes(failed))
		self.assertEqual(frappe.db.count("ToDo"), todos)
		self.assertEqual(valid.sync_status, "Success")
		# a run with a failure does not move the watermark
		self.assertIsNone(esc.get_connection(self.connection).shots[0].last_import)

	def test_failed_requests_are_logged(self):
		frappe.db.set_value(TRANSFORM, self.import_transform, "next_request_expr", None)
		for reply, code in (
			({"body": "<html>Bad Gateway</html>", "status": 502}, "http-status"),
			({"body": "not json"}, "invalid-json"),
			({"json": {"items": []}}, "ValidationError"),
		):
			with self.subTest(code=code):
				self.sync((responses.GET, f"{SERVER}/tasks", reply))
				log = pull_logs(self.connection)[-1]
				self.assertEqual((log.sync_status, codes(log)[-1]), ("Failure", code))
		self.assertEqual(pull_logs(self.connection)[0].response, "<html>Bad Gateway</html>")
		self.assertIsNone(esc.get_connection(self.connection).shots[0].last_import)
		self.assertIsNotNone(frappe.db.get_value("Espresso Sync Connection", self.connection, "last_pull"))

	def test_items_without_an_id_or_a_date_fail_alone(self):
		frappe.db.set_value(TRANSFORM, self.import_transform, "next_request_expr", None)
		self.sync(
			page(
				1,
				{"title": "es no id"},
				task("d1", "es bad date", "someday"),
				task("d2", "es after the failures"),
			)
		)
		self.assertEqual(self.todo("d2").description, "es after the failures")
		logs = pull_logs(self.connection)
		self.assertEqual(
			[(log.sync_status, codes(log)[-1:]) for log in logs[1:]],
			[("Failure", ["no-external-id"]), ("Failure", ["ValidationError"]), ("Success", [])],
		)

	def test_an_import_that_stops_at_maximum_pages_fails(self):
		frappe.db.set_value(TRANSFORM, self.import_transform, "max_pages", 2)
		calls = self.sync(page(1, task("m1", "es first page")), page(2, task("m2", "es second page")))
		self.assertEqual(len(calls), 2)
		self.assertEqual(self.todo("m2").description, "es second page")
		last = pull_logs(self.connection)[-1]
		self.assertEqual((last.sync_status, codes(last)), ("Failure", ["max-pages"]))
		self.assertTrue(last.url.endswith("/tasks?page=3"))
		# the next import reads the pages left from the same Last Import
		self.assertIsNone(esc.get_connection(self.connection).shots[0].last_import)

	def test_a_next_request_of_nulls_ends_the_pages(self):
		frappe.db.set_value(TRANSFORM, self.import_transform, "next_request_expr", '{"cursor": body.next}')
		calls = self.sync(
			(responses.GET, f"{SERVER}/tasks", {"json": {"data": [task("c1", "es c")], "next": None}})
		)
		self.assertEqual(len(calls), 1)
		self.assertIsNotNone(esc.get_connection(self.connection).shots[0].last_import)

	def test_a_bad_next_request_stops_the_pages(self):
		frappe.db.set_value(TRANSFORM, self.import_transform, "next_request_expr", '"page=2"')
		self.sync(page(1, task("n1", "es first page")))
		self.assertEqual(self.todo("n1").description, "es first page")
		self.assertEqual(codes(pull_logs(self.connection)[-1]), ["next-request"])

	def test_the_response_is_checked_as_warnings(self):
		frappe.db.set_value(TRANSFORM, self.import_transform, "next_request_expr", None)
		self.sync(page(1, task("w1", "es warned", done="yes")))
		request = pull_logs(self.connection)[0]
		self.assertEqual(request.sync_status, "Success")
		self.assertEqual(
			[(d["code"], d["severity"]) for d in json.loads(request.diagnostics)],
			[("schema-type", "warning")],
		)
		self.assertEqual(self.todo("w1").description, "es warned")
		# Off checks nothing
		frappe.db.set_value(TRANSFORM, self.import_transform, "runtime_validation", "Off")
		self.sync(page(1, task("w2", "es unchecked", done="yes")))
		self.assertIsNone(pull_logs(self.connection)[-2].diagnostics)

	def test_a_disabled_sync_id_is_not_imported(self):
		frappe.db.set_value(TRANSFORM, self.import_transform, "next_request_expr", None)
		self.sync(page(1, task("x1", "es disabled")))
		row = self.todo("x1").espresso_sync_ids[0]
		frappe.db.set_value("Espresso Sync ID", row.name, "dont_sync", 1)
		self.sync(page(1, task("x1", "es disabled, renamed", "2026-02-01T00:00:00Z")))
		self.assertEqual(self.todo("x1").description, "es disabled")

	def test_skip_when_skips_an_item_before_anything_else(self):
		# done items are skipped, and a skipped item needs no id
		frappe.db.set_value(
			TRANSFORM, self.import_transform, {"next_request_expr": None, "skip_expr": "done"}
		)
		self.sync(
			page(
				1,
				task("s1", "es skip kept"),
				task("s2", "es skip done", done=True),
				{"title": "no id", "done": True},
			)
		)
		self.assertEqual(self.todo("s1").description, "es skip kept")
		self.assertEqual(frappe.db.count("Espresso Sync ID", {"sync_connection": self.connection}), 1)
		logs = pull_logs(self.connection)
		# the request, and the one item imported: a skipped item is not logged
		self.assertEqual(
			[(log.sync_status, bool(log.sync_doc)) for log in logs], [("Success", False), ("Success", True)]
		)

	def test_skip_when_is_true_or_nothing(self):
		frappe.db.set_value(TRANSFORM, self.import_transform, "next_request_expr", None)
		# nothing at all does not skip, and neither does $not of it
		frappe.db.set_value(TRANSFORM, self.import_transform, "skip_expr", "$not(missing)")
		self.sync(page(1, task("n1", "es not skipped")))
		self.todo("n1")
		# $exists is always a boolean
		frappe.db.set_value(TRANSFORM, self.import_transform, "skip_expr", "$not($exists(missing))")
		self.sync(page(1, task("n2", "es skipped")))
		self.assertFalse(
			frappe.db.exists("Espresso Sync ID", {"sync_connection": self.connection, "external_id": "n2"})
		)

	def test_skip_when_reads_what_it_gives_as_jsonata_does(self):
		frappe.db.set_value(TRANSFORM, self.import_transform, "next_request_expr", None)
		for n, (expression, skipped) in enumerate(
			[
				('"x"', True),
				('""', False),
				("1", True),
				("0", False),
				("null", False),
				("[]", False),
				("[1]", True),
				("{}", False),
				('{"a": 1}', True),
				("title", True),
				("missing", False),
				("  ", False),
			]
		):
			with self.subTest(expression):
				frappe.db.set_value(TRANSFORM, self.import_transform, "skip_expr", expression)
				self.sync(page(1, task(f"c{n}", f"es coerced {n}")))
				self.assertEqual(
					bool(
						frappe.db.exists(
							"Espresso Sync ID", {"sync_connection": self.connection, "external_id": f"c{n}"}
						)
					),
					not skipped,
				)

	def test_an_error_in_skip_when_fails_that_item_only(self):
		frappe.db.set_value(
			TRANSFORM, self.import_transform, {"next_request_expr": None, "skip_expr": "$number(title) > 0"}
		)
		self.sync(page(1, task("k1", "es bad"), task("k2", "5"), task("k3", "-1")))
		self.assertEqual(self.todo("k3").description, "-1")
		self.assertFalse(
			frappe.db.exists("Espresso Sync ID", {"sync_connection": self.connection, "external_id": "k2"})
		)
		failed = [log for log in pull_logs(self.connection) if log.sync_status == "Failure"]
		self.assertEqual(len(failed), 1)
		self.assertIn("es bad", failed[0].object)
		# a failure keeps Last Import where it was
		self.assertIsNone(esc.get_connection(self.connection).shots[0].last_import)

	def test_a_draft_transform_is_never_executed(self):
		frappe.db.set_value(TRANSFORM, self.import_transform, "status", "Draft")
		self.assertEqual(self.sync(), [])
		[log] = pull_logs(self.connection)
		self.assertEqual((log.sync_status, codes(log)), ("Failure", ["transform-not-active"]))
		# nor one whose API Spec is no longer the Connection's
		frappe.db.set_value(TRANSFORM, self.import_transform, "status", "Active")
		frappe.db.set_value(schema_api.SPEC, self.spec, "connection", None)
		self.assertEqual(self.sync(), [])
		self.assertEqual(codes(pull_logs(self.connection)[-1]), ["transform-connection"])
		frappe.db.set_value(schema_api.SPEC, self.spec, "connection", self.connection)
		# nor one of another DocType than the shot's
		frappe.db.set_value(TRANSFORM, self.import_transform, "document_type", "Note")
		self.assertEqual(self.sync(), [])
		self.assertEqual(codes(pull_logs(self.connection)[-1]), ["transform-shot"])
		frappe.db.set_value(TRANSFORM, self.import_transform, "document_type", "ToDo")
		# nor can a shot be saved with one
		connection = esc.get_connection(self.connection)
		connection.shots[0].import_transform = self.transform("draft", IMPORT_TASKS, activate=False)
		self.assertRaises(frappe.ValidationError, connection.save)

	def test_a_credential_is_never_sent_off_host(self):
		frappe.db.set_value(TRANSFORM, self.import_transform, "next_request_expr", None)
		calls = self.sync(
			(responses.GET, f"{SERVER}/tasks", {"status": 302, "headers": {"Location": f"{OTHER}/tasks"}}),
			(responses.GET, f"{OTHER}/tasks", {"json": {"data": []}}),
		)
		self.assertEqual(calls[0].request.headers["X-Api-Key"], SECRET)
		self.assertNotIn("X-Api-Key", calls[1].request.headers)
		# and a Connection cannot send them to another host than its Server URL's
		connection = esc.get_connection(self.connection)
		connection.allowed_host = "other.example.invalid"
		self.assertRaises(frappe.ValidationError, connection.save)

	def test_a_sync_request_is_retried(self):
		frappe.db.set_value(TRANSFORM, self.import_transform, "next_request_expr", None)
		with patch.object(safe_fetch.time, "sleep"):
			self.sync(
				(responses.GET, f"{SERVER}/tasks", {"status": 429, "headers": {"Retry-After": "1"}}),
				page(1, task("r1", "es retried")),
			)
		self.assertEqual(self.todo("r1").description, "es retried")


class TestChildTables(SyncTestCase):
	def test_merge_by_key_and_replace(self):
		transform = self.transform(
			"people",
			{
				"direction": "Import",
				"document_type": "Contact",
				"method": "GET",
				"path": "/people",
				"external_id_expr": "name",
				"child_table_policy": "Merge by Key",
				"child_table_keys": json.dumps({"email_ids": "email_id"}),
				"rules": [
					{"ptr": "/first_name", "kind": "field", "expr": "name"},
					{"ptr": "/email_ids", "kind": "collection", "expr": "emails"},
					{"ptr": "/email_ids/email_id", "kind": "field", "expr": "$"},
				],
			},
		)
		add_shot(self.connection, dt="Contact", do_import=1, import_transform=transform)

		def people(*emails):
			return (responses.GET, f"{SERVER}/people", {"json": [{"name": "es-ada", "emails": list(emails)}]})

		def contact_name():
			return frappe.get_all(
				"Espresso Sync ID",
				filters={"sync_connection": self.connection, "external_id": "es-ada"},
				pluck="parent",
			)[0]

		def emails():
			return sorted(row.email_id for row in frappe.get_doc("Contact", contact_name()).get("email_ids"))

		self.sync(people("a@example.invalid"))
		contact: Any = frappe.get_doc("Contact", contact_name())
		contact.append("email_ids", {"email_id": "local@example.invalid"})
		contact.save()
		self.sync(people("a@example.invalid", "c@example.invalid"))
		self.assertEqual(emails(), ["a@example.invalid", "c@example.invalid", "local@example.invalid"])

		frappe.db.set_value(TRANSFORM, transform, "child_table_policy", "Replace")
		self.sync(people("c@example.invalid"))
		self.assertEqual(emails(), ["c@example.invalid"])


class TestExport(SyncTestCase):
	def setUp(self):
		super().setUp()
		add_shot(
			self.connection,
			dt="ToDo",
			do_export=1,
			export_transform=self.transform("export", EXPORT_TASKS),
			update_transform=self.transform("update", UPDATE_TASKS),
		)
		self.start_exports_now()
		self.todos: list[Any] = [
			frappe.get_doc({"doctype": "ToDo", "description": f"es {self._testMethodName} {n}"}).insert()
			for n in (1, 2)
		]

	def external_id(self, todo):
		return frappe.db.get_value(
			"Espresso Sync ID",
			{"sync_connection": self.connection, "parenttype": "ToDo", "parent": todo.name},
			"external_id",
		)

	def test_a_post_then_a_put(self):
		created = [
			(responses.POST, f"{SERVER}/tasks", {"status": 201, "json": {"id": f"x{n}", "title": "t"}})
			for n in (1, 2)
		]
		calls = self.sync(*created)
		self.assertEqual([call.request.method for call in calls], ["POST", "POST"])
		self.assertEqual(
			json.loads(calls[0].request.body), {"title": self.todos[0].description, "done": False}
		)
		self.assertEqual([self.external_id(t) for t in self.todos], ["x1", "x2"])
		logs = pull_logs(self.connection)
		self.assertEqual([(log.sync_status, log.diagnostics) for log in logs], [("Success", None)] * 2)
		self.assertEqual(json.loads(logs[0].object)["title"], self.todos[0].description)

		# unchanged since: nothing is sent; changed: an update, to its own URL
		self.assertEqual(self.sync(), [])
		todo: Any = frappe.get_doc("ToDo", self.todos[1].name)
		todo.status = "Closed"
		todo.save()
		calls = self.sync((responses.PUT, f"{SERVER}/tasks/x2", {"json": {}}))
		self.assertEqual(json.loads(calls[0].request.body)["done"], True)
		self.assertEqual(self.sync(), [])

	def test_enforce_blocks_an_invalid_payload_and_logs_it(self):
		frappe.db.set_value("ToDo", self.todos[0].name, "description", "x" * 200)
		calls = self.sync(
			(responses.POST, f"{SERVER}/tasks", {"status": 201, "json": {"id": "v2"}}),
		)
		self.assertEqual(len(calls), 1)
		# the oldest change first: the second ToDo, then the first, changed since
		[sent, blocked] = pull_logs(self.connection)
		self.assertEqual(
			(blocked.sync_status, codes(blocked)), ("Failure", ["schema-maxLength", "invalid-payload"])
		)
		self.assertEqual(sent.sync_status, "Success")
		# the failed document stays above the watermark, so the next export sends it again
		shot = esc.get_connection(self.connection).shots[0]
		self.assertLess(shot.last_export, frappe.db.get_value("ToDo", self.todos[0].name, "modified"))

		# Warn: sent, and the findings logged
		for title in (f"{self.connection} export", f"{self.connection} update"):
			frappe.db.set_value(TRANSFORM, title, "runtime_validation", "Warn")
		calls = self.sync((responses.POST, f"{SERVER}/tasks", {"status": 201, "json": {"id": "v1"}}))
		self.assertEqual(len(calls), 1)
		warned = pull_logs(self.connection)[-1]
		self.assertEqual((warned.sync_status, codes(warned)), ("Success", ["schema-maxLength"]))

	def test_failures_fail_that_document_only(self):
		calls = self.sync(
			(responses.POST, f"{SERVER}/tasks", {"status": 500, "json": {"error": "boom"}}),
			(responses.POST, f"{SERVER}/tasks", {"status": 201, "body": "created"}),
		)
		self.assertEqual(len(calls), 2)
		[failed, created] = pull_logs(self.connection)
		self.assertEqual((failed.sync_status, codes(failed)), ("Failure", ["http-status"]))
		self.assertEqual((created.sync_status, codes(created)), ("Success", ["no-external-id"]))
		self.assertEqual([self.external_id(t) for t in self.todos], [None, None])

	def test_a_disabled_or_excluded_document_is_not_exported(self):
		todo: Any = frappe.get_doc("ToDo", self.todos[0].name)
		todo.append("espresso_sync_ids", {"sync_connection": self.connection, "dont_sync": 1})
		todo.save()
		frappe.db.set_value("ToDo", self.todos[1].name, "exclude_from_sync", 1)
		self.assertEqual(self.sync(), [])

	def skip(self, expression: str | None):
		for title in (f"{self.connection} export", f"{self.connection} update"):
			frappe.db.set_value(TRANSFORM, title, "skip_expr", expression)

	def test_a_skipped_document_is_not_sent_and_done(self):
		self.skip(f'description = "{self.todos[0].description}"')
		calls = self.sync((responses.POST, f"{SERVER}/tasks", {"status": 201, "json": {"id": "x2"}}))
		self.assertEqual(
			[json.loads(call.request.body)["title"] for call in calls], [self.todos[1].description]
		)
		self.assertEqual([self.external_id(t) for t in self.todos], [None, "x2"])
		# it is not logged, and Last Export moved past it
		self.assertEqual([log.sync_status for log in pull_logs(self.connection)], ["Success"])
		shot = esc.get_connection(self.connection).shots[0]
		self.assertGreaterEqual(shot.last_export, frappe.db.get_value("ToDo", self.todos[1].name, "modified"))

		# so that what changed about the skip does not send it: Resync is for that
		self.skip(None)
		self.assertEqual(self.sync(), [])
		frappe.db.set_value("Espresso Sync Connection", self.connection, "enabled", 1)
		with patch.object(esc, "enqueue_connection_sync") as enqueue:
			esc.resync(self.connection)
		enqueue.assert_called_once_with(self.connection)
		self.assertIsNone(esc.get_connection(self.connection).shots[0].last_export)
		# the sync it queues reads everything: here, what changed since the test began
		self.start_exports_now()
		calls = self.sync((responses.POST, f"{SERVER}/tasks", {"status": 201, "json": {"id": "x1"}}))
		self.assertEqual(
			[json.loads(call.request.body)["title"] for call in calls], [self.todos[0].description]
		)
		self.assertEqual([self.external_id(t) for t in self.todos], ["x1", "x2"])

	def test_the_transform_that_would_send_the_document_is_asked(self):
		everything = 'description != ""'
		# Skip When on the update alone: a document with no id is created, one with an id is not updated
		frappe.db.set_value(TRANSFORM, f"{self.connection} update", "skip_expr", everything)
		created = [
			(responses.POST, f"{SERVER}/tasks", {"status": 201, "json": {"id": f"x{n}"}}) for n in (1, 2)
		]
		self.assertEqual([call.request.method for call in self.sync(*created)], ["POST", "POST"])
		todo: Any = frappe.get_doc("ToDo", self.todos[0].name)
		todo.status = "Closed"
		todo.save()
		self.assertEqual(self.sync(), [])
		# on the create alone: what has an id is updated, a new document is not created
		frappe.db.set_value(TRANSFORM, f"{self.connection} update", "skip_expr", None)
		frappe.db.set_value(TRANSFORM, f"{self.connection} export", "skip_expr", everything)
		# (the closed one was skipped, so done: it is sent when it changes again)
		todo.reload()
		todo.status = "Open"
		todo.save()
		newer: Any = frappe.get_doc(
			{"doctype": "ToDo", "description": f"es {self._testMethodName} new"}
		).insert()
		calls = self.sync((responses.PUT, f"{SERVER}/tasks/x1", {"json": {}}))
		self.assertEqual([(c.request.method, c.request.url) for c in calls], [("PUT", f"{SERVER}/tasks/x1")])
		self.assertIsNone(self.external_id(newer))

	def test_an_error_in_skip_when_fails_that_document_only(self):
		# $number raises for the first (a title that is no number), and is a number for the second
		frappe.db.set_value("ToDo", self.todos[1].name, "description", "5")
		self.skip("$number(description) > 0")
		calls = self.sync()
		self.assertEqual(calls, [])
		[failed] = pull_logs(self.connection)
		self.assertEqual(failed.sync_status, "Failure")
		self.assertEqual(failed.sync_doc, self.todos[0].name)
		# the one that is skipped is done, the one that failed is sent again by the next sync
		shot = esc.get_connection(self.connection).shots[0]
		self.assertLess(shot.last_export, frappe.db.get_value("ToDo", self.todos[0].name, "modified"))

	def test_only_documents_whose_parent_has_an_id_are_sent(self):
		# the opt-in: an id set by hand on the parent, which the child's Skip When asks for
		parent: Any = frappe.get_doc("ToDo", self.todos[0].name)
		parent.append(
			"espresso_sync_ids", {"sync_connection": self.connection, "external_id": "acme/website"}
		)
		parent.save()
		child: Any = frappe.get_doc(
			{
				"doctype": "ToDo",
				"description": f"es {self._testMethodName} child",
				"reference_type": "ToDo",
				"reference_name": parent.name,
			}
		).insert()
		self.skip('$not($exists($syncId("ToDo", reference_name)))')
		calls = self.sync((responses.POST, f"{SERVER}/tasks", {"status": 201, "json": {"id": "c1"}}))
		self.assertEqual([json.loads(call.request.body)["title"] for call in calls], [child.description])
		self.assertEqual(self.external_id(child), "c1")
		# the parent has an id, and no parent of its own: it is skipped, with the other ToDo
		self.assertEqual(self.external_id(parent), "acme/website")
		self.assertIsNone(self.external_id(self.todos[1]))


class TestFollowUp(SyncTestCase):
	"""A Follow-up Transform: a second request for a document, after its create or update."""

	def setUp(self):
		super().setUp()
		self.follow_up = self.transform("follow-up", FOLLOW_UP_TASKS)
		add_shot(
			self.connection,
			dt="ToDo",
			do_export=1,
			export_transform=self.transform("export", EXPORT_TASKS),
			update_transform=self.transform("update", UPDATE_TASKS),
			follow_up_transform=self.follow_up,
		)
		self.start_exports_now()
		self.parent: Any = frappe.get_doc(
			{"doctype": "ToDo", "description": f"es {self._testMethodName} parent"}
		).insert()
		self.child: Any = frappe.get_doc(
			{
				"doctype": "ToDo",
				"description": f"es {self._testMethodName} child",
				"reference_type": "ToDo",
				"reference_name": self.parent.name,
			}
		).insert()
		# the parent changed after the child did: it is sent after it, without an ID to point to yet
		frappe.db.set_value("ToDo", self.parent.name, "priority", "High")

	def created(self, number: int):
		return (responses.POST, f"{SERVER}/tasks", {"status": 201, "json": {"id": f"x{number}", "n": number}})

	def updated(self, number: int):
		return (responses.PUT, f"{SERVER}/tasks/x{number}", {"json": {"id": f"x{number}", "n": number}})

	def link(self, parent_id: str, status: int = 201):
		return (responses.POST, f"{SERVER}/tasks/{parent_id}/links", {"status": status, "json": {}})

	def row(self, todo):
		return frappe.db.get_value(
			"Espresso Sync ID",
			{"sync_connection": self.connection, "parenttype": "ToDo", "parent": todo.name},
			["external_id", "last_synced_modified"],
			as_dict=True,
		)

	def test_the_follow_up_goes_after_every_document_with_the_answer_to_its_request(self):
		calls = self.sync(self.created(1), self.created(2), self.link("x2"))
		# the child first (it changed first), the parent second, and only then the follow-up: the
		# parent's ID is known by then
		self.assertEqual(
			[(call.request.method, call.request.url) for call in calls],
			[("POST", f"{SERVER}/tasks")] * 2 + [("POST", f"{SERVER}/tasks/x2/links")],
		)
		self.assertEqual(json.loads(calls[2].request.body), {"task": 1})
		self.assertEqual([self.row(t).external_id for t in (self.child, self.parent)], ["x1", "x2"])
		logs = pull_logs(self.connection)
		self.assertEqual(
			[(log.sync_status, log.transform) for log in logs],
			[("Success", f"{self.connection} export")] * 2 + [("Success", self.follow_up)],
		)
		self.assertEqual(logs[2].sync_doc, self.child.name)
		# every document is synced now, so nothing is sent again
		self.assertTrue(all(self.row(t).last_synced_modified for t in (self.child, self.parent)))
		self.assertEqual(self.sync(), [])

	def test_a_failed_follow_up_is_sent_again_with_its_update(self):
		calls = self.sync(self.created(1), self.created(2), self.link("x2", status=500))
		self.assertEqual(len(calls), 3)
		logs = pull_logs(self.connection)
		self.assertEqual(
			[(log.sync_status, codes(log)) for log in logs],
			[("Success", []), ("Success", []), ("Failure", ["http-status"])],
		)
		# the child has its ID, and is not synced: the next export sends it again, as an update
		self.assertEqual(self.row(self.child).external_id, "x1")
		self.assertIsNone(self.row(self.child).last_synced_modified)
		shot = esc.get_connection(self.connection).shots[0]
		self.assertLess(shot.last_export, frappe.db.get_value("ToDo", self.child.name, "modified"))
		calls = self.sync(self.updated(1), self.link("x2"))
		self.assertEqual(
			[(call.request.method, call.request.url) for call in calls],
			[("PUT", f"{SERVER}/tasks/x1"), ("POST", f"{SERVER}/tasks/x2/links")],
		)
		self.assertTrue(self.row(self.child).last_synced_modified)
		self.assertEqual(self.sync(), [])

	def test_a_parent_without_an_id_fails_the_follow_up_until_it_has_one(self):
		frappe.db.set_value("ToDo", self.parent.name, "exclude_from_sync", 1)
		calls = self.sync(self.created(1))
		self.assertEqual(len(calls), 1)
		[created, failed] = pull_logs(self.connection)
		self.assertEqual(created.sync_status, "Success")
		self.assertEqual((failed.sync_status, failed.transform), ("Failure", self.follow_up))
		self.assertIn("Path Parameters gives no id", failed.diagnostics)
		self.assertEqual(self.row(self.child).external_id, "x1")
		# the parent is sent after all: the child's follow-up finds its ID, in the same export
		frappe.db.set_value("ToDo", self.parent.name, "exclude_from_sync", 0)
		calls = self.sync(self.updated(1), self.created(2), self.link("x2"))
		self.assertEqual(
			[(call.request.method, call.request.url) for call in calls],
			[
				("PUT", f"{SERVER}/tasks/x1"),
				("POST", f"{SERVER}/tasks"),
				("POST", f"{SERVER}/tasks/x2/links"),
			],
		)
		self.assertEqual(json.loads(calls[2].request.body), {"task": 1})
		self.assertTrue(self.row(self.child).last_synced_modified)

	def test_the_follow_up_reads_the_response_in_skip_when_and_is_skipped_as_done(self):
		frappe.db.set_value(TRANSFORM, self.follow_up, "skip_expr", "reference_name ? $response.n = 1 : true")
		calls = self.sync(self.created(1), self.created(2))
		self.assertEqual(len(calls), 2)
		# a skipped follow-up is not logged, and the document is synced
		self.assertEqual(len(pull_logs(self.connection)), 2)
		self.assertTrue(all(self.row(t).last_synced_modified for t in (self.child, self.parent)))
		self.assertEqual(self.sync(), [])

	def test_a_document_that_is_not_sent_has_no_follow_up(self):
		frappe.db.set_value(
			TRANSFORM, f"{self.connection} export", "skip_expr", "reference_name ? true : false"
		)
		calls = self.sync(self.created(1))
		self.assertEqual([call.request.url for call in calls], [f"{SERVER}/tasks"])
		self.assertIsNone(self.row(self.child))
		self.assertEqual({log.sync_status for log in pull_logs(self.connection)}, {"Success"})

	def test_a_create_that_gives_no_id_has_no_follow_up(self):
		calls = self.sync(
			(responses.POST, f"{SERVER}/tasks", {"status": 201, "json": {"n": 1}}),
			(responses.POST, f"{SERVER}/tasks", {"status": 201, "json": {"n": 2}}),
		)
		self.assertEqual(len(calls), 2)
		self.assertEqual(
			[codes(log) for log in pull_logs(self.connection)], [["no-external-id"], ["no-external-id"]]
		)

	def test_without_a_follow_up_transform_a_document_is_synced_as_it_is_sent(self):
		frappe.db.set_value(
			"Espresso Sync Connection Shot",
			esc.get_connection(self.connection).shots[0].name,
			"follow_up_transform",
			None,
		)
		calls = self.sync(self.created(1), self.created(2))
		self.assertEqual(len(calls), 2)
		self.assertTrue(all(self.row(t).last_synced_modified for t in (self.child, self.parent)))
		self.assertEqual(self.sync(), [])


class TestResync(SyncTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.set_value("Espresso Sync Connection", self.connection, "enabled", 1)
		add_shot(
			self.connection,
			dt="ToDo",
			do_import=1,
			import_transform=self.transform("import", IMPORT_TASKS),
			do_export=1,
			export_transform=self.transform("export", EXPORT_TASKS),
			update_transform=self.transform("update", UPDATE_TASKS),
		)
		# a second shot, which syncs nothing, and a second Connection
		add_shot(self.connection, dt="Contact")
		self.other = make_connection(f"{self.connection} other")
		add_shot(self.other, dt="ToDo")
		self.start_exports_now()
		for name in (self.connection, self.other):
			for shot in esc.get_connection(name).shots:
				for fieldname in ("last_import", "last_export"):
					frappe.db.set_value(sync.SHOT, shot.name, fieldname, self.since, update_modified=False)

	def watermarks(self, name: str | None = None) -> list:
		return [
			(shot.last_import, shot.last_export) for shot in esc.get_connection(name or self.connection).shots
		]

	def test_resync_resets_every_shot_of_the_connection_and_queues_a_sync(self):
		self.assertEqual(self.watermarks(), [(self.since, self.since)] * 2)
		with patch.object(esc, "enqueue_connection_sync") as enqueue:
			returned = esc.resync(self.connection)
		enqueue.assert_called_once_with(self.connection)
		self.assertEqual(self.watermarks(), [(None, None)] * 2)
		# the desk form is refreshed with what is returned: it is not the old watermarks
		self.assertEqual([(s.last_import, s.last_export) for s in returned.shots], [(None, None)] * 2)
		# nothing of another Connection
		self.assertEqual(self.watermarks(self.other), [(self.since, self.since)])

	def test_a_connection_that_is_not_enabled_is_only_reset(self):
		frappe.db.set_value("Espresso Sync Connection", self.connection, "enabled", 0)
		with patch.object(esc, "enqueue_connection_sync") as enqueue:
			esc.resync(self.connection)
		enqueue.assert_not_called()
		self.assertEqual(self.watermarks(), [(None, None)] * 2)

	def test_resync_is_refused_while_the_connection_syncs(self):
		with scheduler.holding_sync_lock(self.connection) as acquired:
			self.assertTrue(acquired)
			with (
				patch.object(esc, "enqueue_connection_sync") as enqueue,
				self.assertRaises(frappe.ValidationError),
			):
				esc.resync(self.connection)
		enqueue.assert_not_called()
		self.assertEqual(self.watermarks(), [(self.since, self.since)] * 2)

	def test_only_a_system_manager_resyncs(self):
		frappe.set_user("Guest")
		with (
			patch.object(esc, "enqueue_connection_sync") as enqueue,
			self.assertRaises(frappe.PermissionError),
		):
			esc.resync(self.connection)
		enqueue.assert_not_called()
		frappe.set_user("Administrator")
		self.assertEqual(self.watermarks(), [(self.since, self.since)] * 2)

	def test_the_action_answers_post_only(self):
		# it writes: a GET would skip the CSRF check, and its changes are rolled back
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[esc.resync_action], ["POST"])


class TestSyncOnlyTab(SyncTestCase):
	def test_a_shot_that_neither_imports_nor_exports_adds_the_sync_tab(self):
		# saving the Connection while it is Enabled gives each shot's DocType its Sync tab
		connection = esc.get_connection(self.connection)
		connection.enabled = 1
		connection.append("shots", {"dt": "Note"})
		with patch.object(esc, "ensure_sync_fields") as ensure:
			connection.save()
		ensure.assert_called_once_with("Note")
		# and a sync of it does nothing: no request, nothing logged
		self.assertEqual(self.sync(), [])
		self.assertEqual(pull_logs(self.connection), [])


class TestTwoWay(SyncTestCase):
	def test_a_document_its_export_skips_is_not_kept_from_an_import(self):
		import_transform = self.transform("import", IMPORT_TASKS, next_request_expr=None)
		export = self.transform("export", EXPORT_TASKS)
		update = self.transform("update", UPDATE_TASKS)
		add_shot(
			self.connection,
			dt="ToDo",
			do_import=1,
			import_transform=import_transform,
			do_export=1,
			export_transform=export,
			update_transform=update,
		)
		self.start_exports_now()
		self.sync(page(1, task("k1", "es kept")))
		# changed here, and the update transform now skips it: nothing will send the change
		todo = self.todo("k1")
		todo.description = "es kept, changed here"
		todo.save()
		frappe.db.set_value(TRANSFORM, update, "skip_expr", 'description != ""')
		# a change in the API is imported over it, not a conflict that stays for ever
		self.sync(page(1, task("k1", "es kept, changed there", "2026-02-01T00:00:00Z")))
		self.assertEqual({log.sync_status for log in pull_logs(self.connection)}, {"Success"})
		self.assertEqual(self.todo("k1").description, "es kept, changed there")
		# while the export does send it, a change made here is kept as it was
		frappe.db.set_value(TRANSFORM, update, "skip_expr", None)
		todo = self.todo("k1")
		todo.description = "es kept, changed here again"
		todo.save()
		self.sync(
			page(1, task("k1", "es kept, changed there too", "2026-03-01T00:00:00Z")),
			(responses.PUT, f"{SERVER}/tasks/k1", {"json": {}}),
		)
		self.assertEqual(self.todo("k1").description, "es kept, changed here again")

	def test_no_echo_loop(self):
		import_transform = self.transform("import", IMPORT_TASKS, next_request_expr=None)
		add_shot(
			self.connection,
			dt="ToDo",
			do_import=1,
			import_transform=import_transform,
			do_export=1,
			export_transform=self.transform("export", EXPORT_TASKS),
			update_transform=self.transform("update", UPDATE_TASKS),
		)
		self.start_exports_now()
		# imported, and not sent back
		calls = self.sync(page(1, task("e1", "es two-way")))
		self.assertEqual([call.request.method for call in calls], ["GET"])

		# changed here: sent once
		todo = self.todo("e1")
		todo.description = "es two-way, changed here"
		todo.save()
		calls = self.sync(
			page(1, task("e1", "es two-way")), (responses.PUT, f"{SERVER}/tasks/e1", {"json": {}})
		)
		self.assertEqual([call.request.method for call in calls], ["GET", "PUT"])

		# changed there: imported, and not sent back
		calls = self.sync(page(1, task("e1", "es two-way, changed there", "2026-02-01T00:00:00Z")))
		self.assertEqual([call.request.method for call in calls], ["GET"])
		self.assertEqual(self.todo("e1").description, "es two-way, changed there")
		self.assertEqual({log.sync_status for log in pull_logs(self.connection)}, {"Success"})

	def test_a_change_made_here_is_not_overwritten(self):
		import_transform = self.transform("import", IMPORT_TASKS, next_request_expr=None)
		add_shot(
			self.connection,
			dt="ToDo",
			do_import=1,
			import_transform=import_transform,
			do_export=1,
			export_transform=self.transform("export", EXPORT_TASKS),
			update_transform=self.transform("update", UPDATE_TASKS),
		)
		self.start_exports_now()
		self.sync(page(1, task("h1", "es here")))

		def change(description: str):
			todo = self.todo("h1")
			todo.description = description
			todo.save()

		def put(description: str, updated: str):
			# the API answers with the object as it now is: newer than what was imported
			reply = {"json": task("h1", description, updated)}
			return (responses.PUT, f"{SERVER}/tasks/h1", reply)

		change("es here, first")
		calls = self.sync(page(1, task("h1", "es here")), put("es here, first", "2026-03-01T00:00:00Z"))
		self.assertEqual([call.request.method for call in calls], ["GET", "PUT"])
		# the API's copy is what was exported: the next import does not read it back over a
		# change made since
		change("es here, second")
		calls = self.sync(
			page(1, task("h1", "es here, first", "2026-03-01T00:00:00Z")),
			put("es here, second", "2026-03-02T00:00:00Z"),
		)
		self.assertEqual([call.request.method for call in calls], ["GET", "PUT"])
		self.assertEqual(json.loads(calls[1].request.body)["title"], "es here, second")
		self.assertEqual(self.todo("h1").description, "es here, second")
		self.assertEqual({log.sync_status for log in pull_logs(self.connection)}, {"Success"})

		# changed in both: the change made here is kept and sent, and the conflict logged
		change("es here, third")
		calls = self.sync(
			page(1, task("h1", "es there", "2026-03-03T00:00:00Z")),
			put("es here, third", "2026-03-04T00:00:00Z"),
		)
		self.assertEqual([call.request.method for call in calls], ["GET", "PUT"])
		self.assertEqual(self.todo("h1").description, "es here, third")
		conflict = next(log for log in pull_logs(self.connection) if log.sync_status == "Failure")
		self.assertEqual(codes(conflict), ["conflict"])
		self.assertEqual(self.sync(page(1, task("h1", "es here, third", "2026-03-04T00:00:00Z")))[1:], [])


class TestExportWatermark(IntegrationTestCase):
	def test_export_watermark(self):
		import datetime

		t = [datetime.datetime(2026, 1, 15, 9, minute) for minute in range(4)]
		self.assertEqual(sync.export_watermark([], None), None)
		self.assertEqual(sync.export_watermark([(t[1], True), (t[2], True)], t[0]), t[2])
		self.assertEqual(sync.export_watermark([(t[1], True), (t[2], False), (t[3], True)], t[0]), t[1])
		# a failure at the same `modified` as a success holds the watermark below both
		self.assertEqual(sync.export_watermark([(t[1], True), (t[1], False)], t[0]), t[0])
		# never back for a success
		self.assertEqual(sync.export_watermark([(t[1], True)], t[3]), t[3])
		# a full export's failure older than the watermark: back to just below it
		just_below = t[1] - datetime.timedelta(microseconds=1)
		self.assertEqual(sync.export_watermark([(t[1], False), (t[3], True)], t[2]), just_below)
		self.assertEqual(sync.export_watermark([(t[0], True), (t[1], False)], t[1]), just_below)
		self.assertEqual(sync.export_watermark([(t[1], False)], None), None)


class TestExportSaved(SyncTestCase):
	"""An import that only links a document to an item is not the API's version of the document."""

	def link_transform(self, **changes) -> str:
		# the item is the ToDo of the same name here: the import maps nothing but its name (and the
		# description a ToDo needs, as it is)
		return self.transform(
			"link",
			{
				**IMPORT_TASKS,
				"rules": [
					{"ptr": "/name", "kind": "field", "expr": "reference"},
					{"ptr": "/description", "kind": "field", "expr": "title"},
				],
			},
			**changes,
		)

	def setup_shot(self, **changes):
		add_shot(
			self.connection,
			dt="ToDo",
			do_import=1,
			import_transform=self.link_transform(**changes),
			do_export=1,
			export_transform=self.transform("export", EXPORT_TASKS),
			update_transform=self.transform("update", UPDATE_TASKS),
		)
		self.start_exports_now()

	def linked_todo(self) -> Any:
		return frappe.get_doc({"doctype": "ToDo", "description": "es linked"}).insert()

	def link_replies(self, todo) -> tuple:
		item = task("link-1", "es linked", reference=todo.name)
		return (
			page(1, item),
			page(2),
			(responses.PUT, f"{SERVER}/tasks/link-1", {"json": task("link-1", "es linked")}),
		)

	def test_what_an_import_only_links_is_sent_by_the_next_export_when_it_says_so(self):
		self.setup_shot(export_saved=1)
		todo = self.linked_todo()
		calls = self.sync(*self.link_replies(todo))
		# the item is the document's, and the document is sent to it as an update of that item
		self.assertEqual([c.request.method for c in calls], ["GET", "GET", "PUT"])
		self.assertEqual(json.loads(calls[2].request.body)["title"], "es linked")
		self.assertEqual(self.todo("link-1").name, todo.name)
		# sent once: the next sync reads the items and sends nothing
		self.assertEqual(
			[
				c.request.method
				for c in self.sync(page(1, task("link-1", "es linked", reference=todo.name)), page(2))
			],
			["GET", "GET"],
		)

	def test_what_an_import_saves_is_not_sent_back_otherwise(self):
		self.setup_shot()
		todo = self.linked_todo()
		calls = self.sync(page(1, task("link-1", "es linked", reference=todo.name)), page(2))
		self.assertEqual([c.request.method for c in calls], ["GET", "GET"])
		self.assertEqual(self.todo("link-1").name, todo.name)
