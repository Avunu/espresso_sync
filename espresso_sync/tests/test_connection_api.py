# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""The portal's Connection endpoints: who may call them, what they answer, and that no
answer holds the API Secret."""

import inspect
import json
from datetime import timedelta
from typing import Any
from unittest.mock import patch

import frappe
import requests
import responses
from frappe.share import add as share_doc
from frappe.utils import get_datetime, now_datetime, set_request

from espresso_sync import scheduler, sync
from espresso_sync.api import connection as api
from espresso_sync.espresso_sync.doctype.espresso_sync_connection import espresso_sync_connection as esc
from espresso_sync.tests.egress import public_dns
from espresso_sync.tests.test_sync import (
	EXPORT_TASKS,
	IMPORT_TASKS,
	OTHER,
	SECRET,
	SERVER,
	SyncTestCase,
	add_shot,
	make_connection,
)

DESK_USER = "es-connection-api-desk@example.com"
MANAGER_USER = "es-connection-api-manager@example.com"
DESK_ROLE = "Espresso Sync Connection API Test Desk Role"
MUTATIONS = {
	"create_connection",
	"save_connection",
	"sync_now",
	"resync",
	"set_enabled",
	"check_connection",
	"save_shot",
	"remove_shot",
	"move_shot",
	"reset_shot",
	"delete_connection",
}


def make_user(email: str, roles: tuple[str, ...] = ()) -> str:
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"roles": [{"role": role} for role in roles],
			}
		).insert(ignore_permissions=True)
	return email


def add_log(
	connection: str,
	status: str = "Success",
	code: str | None = None,
	age_hours: float = 0,
	request: bool = False,
) -> str:
	"""A Pull Log entry of `connection`, written `age_hours` ago: of a document, or of a
	`request`, which has none."""
	diagnostics = [{"severity": "error", "code": code, "message": f"{code} happened"}] if code else None
	name = str(
		frappe.get_doc(
			{
				"doctype": api.PULL_LOG,
				"sync_connection": connection,
				"sync_doctype": "ToDo",
				"sync_direction": "Import",
				"sync_status": status,
				"diagnostics": json.dumps(diagnostics) if diagnostics else None,
			}
		)
		.insert()
		.name
	)
	values: dict[str, Any] = {}
	if status == "Success" and not request:
		# written as the sync writes it: the document may be gone, so its name is not checked
		values["sync_doc"] = "a document"
	if age_hours:
		values["creation"] = now_datetime() - timedelta(hours=age_hours)
	if values:
		frappe.db.set_value(api.PULL_LOG, name, values, update_modified=False)
	return name


class ConnectionApiTestCase(SyncTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("Role", DESK_ROLE):
			frappe.get_doc({"doctype": "Role", "role_name": DESK_ROLE, "desk_access": 1}).insert(
				ignore_permissions=True
			)
		make_user(DESK_USER, (DESK_ROLE,))
		make_user(MANAGER_USER, ("System Manager",))

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def add_import_shot(self, **values) -> str:
		"""A ToDo shot importing through an Active transform; the transform's name."""
		transform = self.transform("import", IMPORT_TASKS)
		add_shot(self.connection, dt="ToDo", do_import=1, import_transform=transform, **values)
		return transform

	def shots(self) -> list[Any]:
		return list(esc.get_connection(self.connection).shots)

	def row(self) -> dict[str, Any]:
		[row] = api.list_status(self.connection)["connections"]
		return row


class TestAccess(ConnectionApiTestCase):
	def endpoints(self):
		name = self.connection
		return {
			"list_status": api.list_status,
			"get_connection": lambda: api.get_connection(name),
			"create_connection": lambda: api.create_connection({"connection_name": f"{name} new"}),
			"save_connection": lambda: api.save_connection(name, {"api_rate_limit": 5}),
			"sync_now": lambda: api.sync_now(name),
			"resync": lambda: api.resync(name),
			"set_enabled": lambda: api.set_enabled(name, 0),
			"check_connection": lambda: api.check_connection(name),
			"cron_preview": lambda: api.cron_preview("0 * * * *"),
			"shot_options": lambda: api.shot_options(name),
			"save_shot": lambda: api.save_shot(name, {"dt": "ToDo"}),
			"remove_shot": lambda: api.remove_shot(name, "none"),
			"move_shot": lambda: api.move_shot(name, "none", 1),
			"reset_shot": lambda: api.reset_shot(name, "none", "Both"),
			"delete_impact": lambda: api.delete_impact(name),
			"delete_connection": lambda: api.delete_connection(name, name),
		}

	def test_every_endpoint_is_covered(self):
		whitelisted = {
			name for name, fn in inspect.getmembers(api, inspect.isfunction) if fn in frappe.whitelisted
		}
		self.assertEqual(whitelisted, set(self.endpoints()))
		self.assertEqual(len(whitelisted), 16)

	def test_what_writes_answers_post_only(self):
		# a GET would skip the CSRF check
		for name in self.endpoints():
			methods = frappe.allowed_http_methods_for_whitelisted_func[getattr(api, name)]
			with self.subTest(endpoint=name):
				self.assertEqual(methods, ["POST"] if name in MUTATIONS else ["GET"])

	def test_only_a_system_manager(self):
		# a share is not enough, as for the Connection itself
		share_doc(api.CONNECTION, self.connection, DESK_USER, read=1, write=1, notify=0)
		with (
			responses.RequestsMock() as rsps,
			patch.object(frappe, "enqueue") as enqueue,
			patch.object(esc, "enqueue_connection_sync") as resync_enqueue,
		):
			for name, call in self.endpoints().items():
				frappe.set_user(DESK_USER)
				with self.subTest(endpoint=name), self.assertRaises(frappe.PermissionError):
					call()
			self.assertEqual(len(rsps.calls), 0)
			enqueue.assert_not_called()
			resync_enqueue.assert_not_called()
		frappe.set_user(MANAGER_USER)
		self.assertEqual(
			[row["name"] for row in api.list_status(self.connection)["connections"]], [self.connection]
		)
		self.assertIn(self.connection, [row["name"] for row in api.list_status()["connections"]])
		self.assertEqual(api.get_connection(self.connection)["name"], self.connection)

	def test_a_connection_that_does_not_exist(self):
		for name in ("list_status", "get_connection", "shot_options", "delete_impact"):
			with self.subTest(endpoint=name), self.assertRaises(frappe.DoesNotExistError):
				getattr(api, name)("ES No Such Connection")


class TestStatus(ConnectionApiTestCase):
	def test_idle_queued_and_running(self):
		self.assertEqual(self.row()["state"], "idle")
		with patch.object(api, "is_job_enqueued", return_value=True) as enqueued:
			self.assertEqual(self.row()["state"], "queued")
			enqueued.assert_called_with(scheduler.sync_job_id(self.connection))
		# the lock is read from another Lock object than the one that holds it
		with scheduler.holding_sync_lock(self.connection) as acquired:
			self.assertTrue(acquired)
			self.assertEqual(self.row()["state"], "running")
			self.assertEqual(api.delete_impact(self.connection)["state"], "running")
		self.assertEqual(self.row()["state"], "idle")

	def test_a_job_that_was_never_queued_is_not_queued(self):
		self.assertFalse(api.is_job_enqueued(scheduler.sync_job_id(self.connection)))

	def test_the_row(self):
		self.add_import_shot()
		row = self.row()
		self.assertEqual(
			{key: row[key] for key in ("name", "enabled", "server_url", "sync_frequency", "shots")},
			{
				"name": self.connection,
				"enabled": 0,
				"server_url": SERVER,
				"sync_frequency": "Manual",
				"shots": 1,
			},
		)
		self.assertEqual((row["last_pull"], row["last_sync_attempt"], row["next_run"]), (None, None, None))
		self.assertEqual((row["problems"], row["last_failure"]), ([], None))
		self.assertEqual(
			[
				row[key]
				for key in ("failures_last_run", "successes_last_run", "failures_24h", "successes_24h")
			],
			[0, 0, 0, 0],
		)

	def test_the_counts_respect_the_last_attempt(self):
		add_log(self.connection, "Failure", "http-status", age_hours=30)
		add_log(self.connection, "Failure", "conflict", age_hours=3)
		add_log(self.connection, "Success", age_hours=3)
		add_log(self.connection, "Success")
		# a request that succeeded synced no document: it is not counted
		add_log(self.connection, "Success", request=True)
		add_log(self.connection, "Success", age_hours=3, request=True)
		latest = add_log(self.connection, "Failure", "invalid-payload")
		# nothing was attempted: nothing is of the last run
		row = self.row()
		self.assertEqual((row["failures_last_run"], row["successes_last_run"]), (0, 0))
		self.assertEqual((row["failures_24h"], row["successes_24h"]), (2, 2))
		attempt = now_datetime() - timedelta(hours=1)
		frappe.db.set_value(api.CONNECTION, self.connection, "last_sync_attempt", attempt)
		row = self.row()
		self.assertEqual((row["failures_last_run"], row["successes_last_run"]), (1, 1))
		self.assertEqual(get_datetime(row["last_sync_attempt"]), attempt)
		self.assertEqual(
			{key: row["last_failure"][key] for key in ("name", "code", "message")},
			{"name": latest, "code": "invalid-payload", "message": "invalid-payload happened"},
		)
		# the entries of another Connection are not counted
		other = make_connection(f"{self.connection} other")
		[other_row] = api.list_status(other)["connections"]
		self.assertEqual((other_row["failures_24h"], other_row["last_failure"]), (0, None))

	def test_the_last_error_of_diagnostics(self):
		warning = {"severity": "warning", "code": "w", "message": "a warning"}
		error = {"severity": "error", "code": "e", "message": "x" * 400}
		self.assertEqual(api.last_error(json.dumps([error, warning])), ("e", "x" * 300))
		self.assertEqual(api.last_error([warning]), ("w", "a warning"))
		for nothing in (None, "", "not json", "{}", "[]", [1]):
			with self.subTest(diagnostics=nothing):
				self.assertEqual(api.last_error(nothing), ("", ""))

	def test_the_next_run_of_a_cron_rule(self):
		doc = esc.get_connection(self.connection)
		doc.update({"sync_frequency": "Cron", "cron_rule": "0 3 * * *"})
		doc.save()
		# not while it is paused
		self.assertIsNone(self.row()["next_run"])
		api.set_enabled(self.connection, 1)
		next_run = get_datetime(self.row()["next_run"])
		assert next_run is not None
		self.assertEqual((next_run.hour, next_run.minute), (3, 0))
		# overdue: the time it should have run at, in the past
		attempt = now_datetime() - timedelta(days=3)
		frappe.db.set_value(api.CONNECTION, self.connection, "last_sync_attempt", attempt)
		overdue = get_datetime(self.row()["next_run"])
		assert overdue is not None
		self.assertLess(overdue, now_datetime() - timedelta(days=1))
		# a rule that is none, and one that is and never fires: neither keeps the row from being read
		for rule in ("not a rule", "0 0 30 2 *"):
			with self.subTest(rule=rule):
				frappe.db.set_value(api.CONNECTION, self.connection, "cron_rule", rule)
				self.assertIsNone(self.row()["next_run"])

	def test_what_is_wrong_with_a_shot(self):
		transform = self.add_import_shot()
		[shot] = self.shots()
		other = make_connection(f"{self.connection} other")

		def problems() -> list[tuple[str, str | None]]:
			found = self.row()["problems"]
			self.assertTrue(all(problem["doctype"] == "ToDo" and problem["message"] for problem in found))
			return [(problem["code"], problem["transform"]) for problem in found]

		def with_value(doctype: str, name: str, fieldname: str, value: Any) -> list:
			before = frappe.db.get_value(doctype, name, fieldname)
			frappe.db.set_value(doctype, name, fieldname, value, update_modified=False)
			found = problems()
			frappe.db.set_value(doctype, name, fieldname, before, update_modified=False)
			return found

		self.assertEqual(problems(), [])
		self.assertEqual(
			with_value(api.TRANSFORM, transform, "status", "Draft"), [("transform-not-active", transform)]
		)
		self.assertEqual(
			with_value(api.TRANSFORM, transform, "direction", "Export"), [("transform-direction", transform)]
		)
		self.assertEqual(
			with_value(api.TRANSFORM, transform, "document_type", "Contact"),
			[("transform-doctype", transform)],
		)
		self.assertEqual(
			with_value(api.SPEC, self.spec, "connection", other), [("transform-connection", transform)]
		)
		self.assertEqual(
			with_value(sync.SHOT, shot.name, "import_transform", "ES Gone"),
			[("missing-transform", "ES Gone")],
		)
		self.assertEqual(
			with_value(sync.SHOT, shot.name, "import_transform", None), [("missing-transform", None)]
		)
		# a transform of a direction that is off is not read
		frappe.db.set_value(sync.SHOT, shot.name, "do_import", 0, update_modified=False)
		self.assertEqual(with_value(api.TRANSFORM, transform, "status", "Draft"), [])


class TestConnection(ConnectionApiTestCase):
	def test_the_answer_has_no_secret(self):
		self.add_import_shot()
		self.transform("draft export", EXPORT_TASKS, activate=False)
		answer = api.get_connection(self.connection)
		text = frappe.as_json(answer)
		self.assertNotIn(SECRET, text)
		self.assertNotIn("**", text)
		self.assertNotIn("api_secret", text)
		self.assertTrue(answer["has_secret"])
		self.assertEqual(
			{key: answer[key] for key in ("name", "server_url", "allowed_host", "auth_type", "api_key")},
			{
				"name": self.connection,
				"server_url": SERVER,
				"allowed_host": "api.example.invalid",
				"auth_type": "Header-based",
				"api_key": "X-Api-Key",
			},
		)
		self.assertEqual(answer["setup"], {"specs": 1, "transforms": 2, "active_transforms": 1})
		[shot] = answer["shots"]
		self.assertEqual((shot["dt"], shot["do_import"], shot["do_export"]), ("ToDo", 1, 0))
		self.assertEqual(answer["modified"], str(esc.get_connection(self.connection).modified))
		# the status holds none either
		self.assertNotIn(SECRET, frappe.as_json(api.list_status(self.connection)))

	def test_the_spec_suggests_an_authentication(self):
		# the tasks spec declares no security scheme, so it suggests nothing
		self.assertIsNone(api.get_connection(self.connection)["auth_hints"])
		hint = {
			"scheme": "basic",
			"required": True,
			"note": "Basic",
			"suggestion": {"auth_type": "Basic"},
		}
		frappe.db.set_value(
			api.SPEC,
			self.spec,
			"auth_hints",
			json.dumps(
				[{"scheme": "oauth", "suggestion": None}, {**hint, "required": False, "scheme": "b2"}, hint]
			),
		)
		self.assertEqual(
			api.get_connection(self.connection)["auth_hints"],
			{"spec": self.spec, "scheme": "basic", "note": "Basic", "auth_type": "Basic", "api_key": None},
		)
		frappe.db.set_value(api.SPEC, self.spec, "auth_hints", "{}")
		self.assertIsNone(api.get_connection(self.connection)["auth_hints"])
		other = make_connection(f"{self.connection} other")
		answer = api.get_connection(other)
		self.assertIsNone(answer["auth_hints"])
		self.assertEqual(answer["setup"], {"specs": 0, "transforms": 0, "active_transforms": 0})

	def update(self, **values):
		"""What a REST update does: the stored document, updated with what was sent, saved."""
		doc = frappe.get_doc(api.CONNECTION, self.connection)
		doc.update(values)
		doc.save()

	def test_an_update_without_the_secret_keeps_it(self):
		self.update(api_rate_limit=30)
		doc = esc.get_connection(self.connection)
		self.assertEqual(doc.get_password("api_secret"), SECRET)
		self.assertEqual(doc.api_rate_limit, 30)
		self.assertTrue(api.get_connection(self.connection)["has_secret"])

	def test_a_connection_is_made_paused_and_answered_without_its_secret(self):
		name = f"{self.connection} made"
		frappe.delete_doc_if_exists(api.CONNECTION, name, force=True)
		values = {
			"connection_name": name,
			"server_url": SERVER,
			"auth_type": "Header-based",
			"api_key": "X-Api-Key",
			"api_secret": SECRET,
		}
		frappe.set_user(MANAGER_USER)
		answer = api.create_connection(json.dumps(values))
		text = frappe.as_json(answer)
		for secret in (SECRET, "**", "api_secret"):
			self.assertNotIn(secret, text)
		self.assertEqual(
			{key: answer[key] for key in ("name", "enabled", "sync_frequency", "allowed_host", "has_secret")},
			{
				"name": name,
				"enabled": 0,
				"sync_frequency": "Manual",
				"allowed_host": "api.example.invalid",
				"has_secret": True,
			},
		)
		self.assertEqual(esc.get_connection(name).get_password("api_secret"), SECRET)
		# what a Connection is made without, and with
		refused = (
			{**values, "connection_name": f"{name} 2", "server_url": "ftp://files.example.invalid"},
			{**values, "connection_name": f"{name} 2", "enabled": 1},
			{**values, "connection_name": f"{name} 2", "shots": [{"dt": "ToDo"}]},
			json.dumps([values]),
		)
		for index, other in enumerate(refused):
			with self.subTest(index=index), self.assertRaises(frappe.ValidationError):
				api.create_connection(other)
		self.assertFalse(frappe.db.exists(api.CONNECTION, f"{name} 2"))

	def test_a_save_sets_the_settings_and_answers_without_the_secret(self):
		frappe.set_user(MANAGER_USER)
		modified = api.get_connection(self.connection)["modified"]
		values = {"api_rate_limit": 30, "sync_frequency": "Cron", "cron_rule": "0 3 * * *"}
		answer = api.save_connection(self.connection, json.dumps(values), modified)
		text = frappe.as_json(answer)
		for secret in (SECRET, "**", "api_secret"):
			self.assertNotIn(secret, text)
		self.assertEqual({key: answer[key] for key in values}, values)
		self.assertTrue(answer["has_secret"])
		self.assertNotEqual(answer["modified"], modified)
		self.assertEqual(esc.get_connection(self.connection).get_password("api_secret"), SECRET)
		# the secret is set by a new one, and removed by an empty one
		self.assertTrue(api.save_connection(self.connection, {"api_secret": "another"})["has_secret"])
		self.assertEqual(esc.get_connection(self.connection).get_password("api_secret"), "another")
		self.assertFalse(api.save_connection(self.connection, {"api_secret": ""})["has_secret"])
		self.assertFalse(
			esc.get_connection(self.connection).get_password("api_secret", raise_exception=False)
		)

	def test_a_save_that_is_refused(self):
		frappe.set_user(MANAGER_USER)
		before = api.get_connection(self.connection)
		refused = (
			# what has an endpoint of its own, and what the Connection's validation refuses
			{"enabled": 1},
			{"shots": []},
			{"last_pull": None},
			{"sync_frequency": "Cron", "cron_rule": "0 0 30 2 *"},
			{"server_url": "ftp://files.example.invalid"},
			"[]",
		)
		for values in refused:
			with self.subTest(values=values), self.assertRaises(frappe.ValidationError):
				api.save_connection(self.connection, values)
		# and a save over somebody else's
		with self.assertRaises(frappe.TimestampMismatchError):
			api.save_connection(self.connection, {"api_rate_limit": 9}, "2020-01-01 00:00:00.000000")
		self.assertEqual(api.get_connection(self.connection), before)

	def test_an_update_with_an_empty_secret_removes_it(self):
		self.update(api_secret="")
		self.assertFalse(
			esc.get_connection(self.connection).get_password("api_secret", raise_exception=False)
		)
		answer = api.get_connection(self.connection)
		self.assertFalse(answer["has_secret"])
		self.assertNotIn("api_secret", answer)


class TestActions(ConnectionApiTestCase):
	def test_sync_now_queues_an_enabled_connection(self):
		with patch.object(frappe, "enqueue") as enqueue:
			with self.assertRaises(frappe.ValidationError):
				api.sync_now(self.connection)
			enqueue.assert_not_called()
			api.set_enabled(self.connection, 1)
			row = api.sync_now(self.connection)
			scheduler.enqueue_connection_sync(self.connection)
		# the job a scheduled sync runs
		[sync_now, scheduled] = enqueue.call_args_list
		self.assertEqual(sync_now, scheduled)
		self.assertEqual((row["name"], row["enabled"]), (self.connection, 1))

	def test_resync_resets_the_shots_and_says_nothing(self):
		self.add_import_shot()
		[shot] = self.shots()
		frappe.db.set_value(sync.SHOT, shot.name, "last_import", self.since, update_modified=False)
		frappe.db.set_value(api.CONNECTION, self.connection, "enabled", 1)
		frappe.clear_messages()
		with patch.object(esc, "enqueue_connection_sync") as enqueue:
			row = api.resync(self.connection)
		enqueue.assert_called_once_with(self.connection)
		self.assertEqual(row["name"], self.connection)
		self.assertIsNone(self.shots()[0].last_import)
		# the portal shows its own notice
		self.assertEqual(frappe.local.message_log, [])

	def test_resync_is_refused_while_the_connection_syncs(self):
		with (
			scheduler.holding_sync_lock(self.connection),
			patch.object(esc, "enqueue_connection_sync") as enqueue,
			self.assertRaises(frappe.ValidationError),
		):
			api.resync(self.connection)
		enqueue.assert_not_called()

	def test_a_connection_with_a_draft_transform_is_paused_and_not_enabled(self):
		transform = self.add_import_shot()
		self.assertEqual(api.set_enabled(self.connection, 1)["enabled"], 1)
		frappe.db.set_value(api.TRANSFORM, transform, "status", "Draft")
		row = api.set_enabled(self.connection, 0)
		self.assertEqual((row["enabled"], row["problems"][0]["code"]), (0, "transform-not-active"))
		self.assertEqual(frappe.db.get_value(api.CONNECTION, self.connection, "enabled"), 0)
		with self.assertRaises(frappe.ValidationError):
			api.set_enabled(self.connection, 1)
		self.assertEqual(frappe.db.get_value(api.CONNECTION, self.connection, "enabled"), 0)

	def test_cron_preview(self):
		answer = api.cron_preview("30 2 * * *")
		self.assertTrue(answer["valid"])
		times = [value for value in map(get_datetime, answer["next"]) if value]
		self.assertEqual(len(times), 3)
		self.assertEqual(times, sorted(times))
		self.assertTrue(all(value and (value.hour, value.minute) == (2, 30) for value in times))
		self.assertEqual(len(api.cron_preview("* * * * *", count=99)["next"]), 10)
		self.assertEqual(len(api.cron_preview("* * * * *", count=0)["next"]), 1)
		for rule in ("", "every day", "61 * * * *", "0 0 30 2 *", "0 0 31 4 *"):
			with self.subTest(rule=rule):
				self.assertEqual(api.cron_preview(rule), {"valid": False, "next": []})


class TestCheckConnection(ConnectionApiTestCase):
	def check(self, *replies, path: str | None = None) -> tuple[dict[str, Any], list]:
		with responses.RequestsMock() as rsps:
			for url, kwargs in replies:
				rsps.add(responses.GET, url, **kwargs)
			answer = api.check_connection(self.connection, path)
			calls = list(rsps.calls)
		# whatever the answer, it holds no credential and nothing is logged
		self.assertNotIn(SECRET, frappe.as_json(answer))
		self.assertEqual(frappe.db.count(api.PULL_LOG, {"sync_connection": self.connection}), 0)
		return answer, calls

	def test_every_verdict(self):
		for status, verdict in ((200, "ok"), (201, "ok"), (401, "auth"), (403, "auth"), (404, "reachable")):
			with self.subTest(status=status):
				answer, [call] = self.check((SERVER, {"status": status, "json": {"token": SECRET}}))
				self.assertEqual((answer["verdict"], answer["status"]), (verdict, status))
				self.assertEqual(answer["ok"], verdict == "ok")
				self.assertEqual(call.request.headers["X-Api-Key"], SECRET)
				self.assertIsNone(answer["error"])
		answer, _calls = self.check((SERVER, {"status": 503}))
		self.assertEqual(
			(answer["verdict"], answer["ok"], answer["reason"]), ("error", False, "Service Unavailable")
		)
		self.assertEqual((answer["host"], answer["credentials_sent"]), ("api.example.invalid", True))
		self.assertGreaterEqual(answer["elapsed_ms"], 0)
		self.assertEqual(
			set(answer),
			{"ok", "verdict", "status", "reason", "elapsed_ms", "host", "credentials_sent", "error"},
		)

	def test_a_request_that_is_not_answered(self):
		error = requests.ConnectionError(f"refused, sent with X-Api-Key: {SECRET} ({SECRET}) " + "x" * 400)
		answer, _calls = self.check((SERVER, {"body": error}))
		self.assertEqual((answer["verdict"], answer["ok"], answer["status"]), ("unreachable", False, None))
		self.assertIn("refused", answer["error"])
		self.assertLessEqual(len(answer["error"]), 300)
		# an address the guard refuses is one too
		with public_dns("10.0.0.8"):
			answer, calls = self.check()
		self.assertEqual((answer["verdict"], calls), ("unreachable", []))
		self.assertTrue(answer["error"])

	def test_too_many_requests_is_not_waited_for(self):
		answer, calls = self.check((SERVER, {"status": 429, "headers": {"Retry-After": "60"}}))
		self.assertEqual((answer["verdict"], len(calls)), ("reachable", 1))

	def test_the_test_requests_of_an_address_are_limited(self):
		request, request_ip = (
			getattr(frappe.local, "request", None),
			getattr(frappe.local, "request_ip", None),
		)
		self.addCleanup(setattr, frappe.local, "request", request)
		self.addCleanup(setattr, frappe.local, "request_ip", request_ip)
		cache = frappe.cache
		assert cache is not None
		self.addCleanup(cache.delete_keys, "rl:espresso_sync.api.connection")
		set_request(method="POST", path="/api/method/espresso_sync.api.connection.check_connection")
		frappe.local.request_ip = "203.0.113.7"
		with responses.RequestsMock() as rsps:
			rsps.add(responses.GET, SERVER, json={})
			for _index in range(10):
				self.assertTrue(api.check_connection(self.connection)["ok"])
			with self.assertRaises(frappe.RateLimitExceededError):
				api.check_connection(self.connection)
			self.assertEqual(len(rsps.calls), 10)

	def test_a_path_under_the_server_url(self):
		answer, [call] = self.check((f"{SERVER}/status", {"json": {}}), path="/status")
		self.assertEqual((answer["verdict"], call.request.url), ("ok", f"{SERVER}/status"))
		_answer, [call] = self.check((f"{SERVER}/status", {"json": {}}), path="status")
		self.assertEqual(call.request.url, f"{SERVER}/status")
		for path in (f"{OTHER}/tasks", "//other.example.invalid/tasks", "\\\\other.example.invalid", "a\\b"):
			with self.subTest(path=path), self.assertRaises(frappe.ValidationError):
				self.check(path=path)

	def test_the_url_of_the_test_request(self):
		paths = {
			"": SERVER,
			"  ": SERVER,
			"/status": f"{SERVER}/status",
			# a colon in the first segment is no scheme, and `//` further on names no host
			"items:search?q=a": f"{SERVER}/items:search?q=a",
			"a//b?next=https://x.example.invalid/#top": f"{SERVER}/a//b?next=https://x.example.invalid/",
			"https:other": f"{SERVER}/https:other",
		}
		for path, url in paths.items():
			with self.subTest(path=path):
				self.assertEqual(api.check_url(SERVER, path), url)
		# the Server URL's own query stays the query, after its own path
		self.assertEqual(
			api.check_url("https://h.example/v1/?k=v", "status"), "https://h.example/v1/status?k=v"
		)
		self.assertEqual(
			api.check_url("https://h.example/v1?k=v", "/status?a=b"), "https://h.example/v1/status?k=v&a=b"
		)
		self.assertEqual(api.check_url("https://h.example", "status"), "https://h.example/status")

	def test_the_credentials_stay_on_the_allowed_host(self):
		answer, calls = self.check(
			(SERVER, {"status": 302, "headers": {"Location": f"{OTHER}/tasks"}}),
			(f"{OTHER}/tasks", {"json": {}}),
		)
		self.assertEqual(answer["verdict"], "ok")
		self.assertEqual(calls[0].request.headers["X-Api-Key"], SECRET)
		self.assertNotIn("X-Api-Key", calls[1].request.headers)
		# a Connection without credentials sends none
		frappe.db.set_value(api.CONNECTION, self.connection, "api_key", None)
		answer, [call] = self.check((SERVER, {"json": {}}))
		self.assertFalse(answer["credentials_sent"])
		self.assertNotIn("X-Api-Key", call.request.headers)


class TestShots(ConnectionApiTestCase):
	def test_shot_options_include_drafts(self):
		self.assertEqual(api.shot_options(make_connection(f"{self.connection} other")), [])
		active = self.transform("import", IMPORT_TASKS)
		draft = self.transform("export", EXPORT_TASKS, activate=False)
		options = {option["name"]: option for option in api.shot_options(self.connection)}
		self.assertEqual(set(options), {active, draft})
		self.assertEqual(
			options[draft],
			{
				"name": draft,
				"direction": "Export",
				"document_type": "ToDo",
				"status": "Draft",
				"api_spec": self.spec,
			},
		)
		self.assertEqual(options[active]["status"], "Active")

	def test_a_shot_is_added_and_changed(self):
		transform = self.transform("import", IMPORT_TASKS)
		answer = api.save_shot(self.connection, json.dumps({"dt": "ToDo"}))
		[shot] = answer["shots"]
		self.assertEqual(
			(shot["dt"], shot["idx"], shot["do_import"], shot["import_transform"]), ("ToDo", 1, 0, None)
		)
		self.assertEqual(answer["modified"], str(esc.get_connection(self.connection).modified))
		frappe.db.set_value(sync.SHOT, shot["name"], "last_import", self.since, update_modified=False)
		# neither the DocType nor the watermarks are taken from the client
		answer = api.save_shot(
			self.connection,
			{
				"dt": "Contact",
				"do_import": 1,
				"import_transform": transform,
				"export_transform": "",
				"last_import": None,
				"last_export": "2020-01-01 00:00:00",
			},
			name=shot["name"],
		)
		[saved] = self.shots()
		self.assertEqual((saved.dt, saved.do_import, saved.import_transform), ("ToDo", 1, transform))
		self.assertEqual((saved.last_import, saved.last_export), (self.since, None))
		self.assertEqual(answer["shots"][0]["last_import"], str(self.since))

	def test_a_shot_that_is_refused(self):
		draft = self.transform("draft", IMPORT_TASKS, activate=False)
		[shot] = api.save_shot(self.connection, {"dt": "ToDo"})["shots"]
		refused = (
			# a second shot of the DocType, no DocType, not a shot, a shot of no Connection
			lambda: api.save_shot(self.connection, {"dt": "ToDo"}),
			lambda: api.save_shot(self.connection, {"do_import": 0}),
			lambda: api.save_shot(self.connection, "[]"),
			lambda: api.save_shot(self.connection, {"do_import": 0}, name="none"),
			# what the Connection's validation refuses
			lambda: api.save_shot(self.connection, {"do_import": 1}, name=shot["name"]),
			lambda: api.save_shot(
				self.connection, {"do_import": 1, "import_transform": draft}, name=shot["name"]
			),
		)
		for index, call in enumerate(refused):
			with self.subTest(index=index), self.assertRaises(frappe.ValidationError):
				call()
		self.assertEqual([(row.dt, row.do_import) for row in self.shots()], [("ToDo", 0)])

	def test_the_shots_do_not_change_while_the_connection_syncs(self):
		[shot] = api.save_shot(self.connection, {"dt": "ToDo"})["shots"]
		api.save_shot(self.connection, {"dt": "Contact"})
		calls = (
			lambda: api.save_shot(self.connection, {"dt": "Note"}),
			lambda: api.remove_shot(self.connection, shot["name"]),
			lambda: api.move_shot(self.connection, shot["name"], 1),
			lambda: api.reset_shot(self.connection, shot["name"], "Both"),
		)
		with scheduler.holding_sync_lock(self.connection) as acquired:
			self.assertTrue(acquired)
			for index, call in enumerate(calls):
				with self.subTest(index=index), self.assertRaises(frappe.ValidationError):
					call()
		self.assertEqual([row.dt for row in self.shots()], ["ToDo", "Contact"])
		# and they do again when it is done
		self.assertEqual(len(api.remove_shot(self.connection, shot["name"])["shots"]), 1)

	def test_a_change_keeps_what_a_sync_wrote_since_the_connection_was_read(self):
		[shot] = api.save_shot(self.connection, {"dt": "ToDo"})["shots"]
		api.save_shot(self.connection, {"dt": "Contact"})
		# read before a sync ended, which then wrote how far it came
		stale = api.get_doc(self.connection, "write")
		values = {"last_import": self.since, "last_export": self.since}
		frappe.db.set_value(sync.SHOT, shot["name"], values, update_modified=False)
		calls = (
			lambda: api.save_shot(self.connection, {"do_import": 0}, shot["name"]),
			lambda: api.move_shot(self.connection, shot["name"], 1),
			lambda: api.save_shot(self.connection, {"dt": "Note"}),
		)
		for index, call in enumerate(calls):
			with self.subTest(index=index), patch.object(api, "get_doc", return_value=stale):
				answer = call()
			saved = next(row for row in answer["shots"] if row["name"] == shot["name"])
			self.assertEqual((saved["last_import"], saved["last_export"]), (str(self.since),) * 2)
			stored = frappe.db.get_value(sync.SHOT, shot["name"], ["last_import", "last_export"])
			self.assertEqual(stored, (self.since, self.since))

	def test_shots_move_and_are_removed(self):
		names = {
			doctype: api.save_shot(self.connection, {"dt": doctype})["shots"][-1]["name"]
			for doctype in ("ToDo", "Contact", "Note")
		}

		def order() -> list[tuple[str, int]]:
			return [(row.dt, row.idx) for row in self.shots()]

		answer = api.move_shot(self.connection, names["Note"], -1)
		self.assertEqual([shot["dt"] for shot in answer["shots"]], ["ToDo", "Note", "Contact"])
		self.assertEqual(order(), [("ToDo", 1), ("Note", 2), ("Contact", 3)])
		api.move_shot(self.connection, names["ToDo"], 1)
		self.assertEqual(order(), [("Note", 1), ("ToDo", 2), ("Contact", 3)])
		for name, by in ((names["Note"], -1), (names["Contact"], 1), (names["ToDo"], 2), ("none", 1)):
			with self.subTest(name=name, by=by), self.assertRaises(frappe.ValidationError):
				api.move_shot(self.connection, name, by)
		answer = api.remove_shot(self.connection, names["Note"])
		self.assertEqual(
			[(shot["dt"], shot["idx"]) for shot in answer["shots"]], [("ToDo", 1), ("Contact", 2)]
		)
		self.assertEqual(order(), [("ToDo", 1), ("Contact", 2)])
		with self.assertRaises(frappe.ValidationError):
			api.remove_shot(self.connection, names["Note"])

	def test_a_shot_is_reset_one_direction_at_a_time(self):
		[shot] = api.save_shot(self.connection, {"dt": "ToDo"})["shots"]
		other = make_connection(f"{self.connection} other")
		[other_shot] = api.save_shot(other, {"dt": "ToDo"})["shots"]

		def stamp():
			for name in (shot["name"], other_shot["name"]):
				values = {"last_import": self.since, "last_export": self.since}
				frappe.db.set_value(sync.SHOT, name, values, update_modified=False)

		def watermarks(connection: str) -> tuple:
			[row] = esc.get_connection(connection).shots
			return row.last_import, row.last_export

		expected = {"Import": (None, self.since), "Export": (self.since, None), "Both": (None, None)}
		modified = esc.get_connection(self.connection).shots[0].modified
		for direction, left in expected.items():
			stamp()
			with self.subTest(direction=direction), patch.object(frappe, "enqueue") as enqueue:
				[answer] = api.reset_shot(self.connection, shot["name"], direction)["shots"]
				self.assertEqual(watermarks(self.connection), left)
				self.assertEqual(
					(answer["last_import"], answer["last_export"]),
					tuple(str(value) if value else None for value in left),
				)
				enqueue.assert_not_called()
		# the shot is not changed, so its next export is not of everything for that alone
		self.assertEqual(esc.get_connection(self.connection).shots[0].modified, modified)
		self.assertEqual(watermarks(other), (self.since, self.since))
		stamp()
		# a shot of another Connection, and a direction that is none
		for name, direction in ((other_shot["name"], "Both"), (shot["name"], "Sideways")):
			with self.subTest(name=name, direction=direction), self.assertRaises(frappe.ValidationError):
				api.reset_shot(self.connection, name, direction)
		self.assertEqual(watermarks(other), (self.since, self.since))
		self.assertEqual(watermarks(self.connection), (self.since, self.since))


class TestDelete(ConnectionApiTestCase):
	def setUp(self):
		super().setUp()
		add_log(self.connection, "Failure", "http-status")
		add_log(self.connection)
		self.linked = frappe.get_doc({"doctype": "ToDo", "description": "es connection api linked"}).insert()
		self.linked.append("espresso_sync_ids", {"sync_connection": self.connection, "external_id": "d1"})
		self.linked.save()

	def exists(self) -> bool:
		return bool(frappe.db.exists(api.CONNECTION, self.connection))

	def test_the_impact(self):
		self.transform("import", IMPORT_TASKS)
		self.assertEqual(
			api.delete_impact(self.connection),
			{"specs": [self.spec], "transforms": 1, "logs": 2, "links": 1, "state": "idle"},
		)
		other = make_connection(f"{self.connection} other")
		self.assertEqual(
			api.delete_impact(other), {"specs": [], "transforms": 0, "logs": 0, "links": 0, "state": "idle"}
		)

	def test_a_connection_with_an_api_spec_is_not_deleted(self):
		with self.assertRaises(frappe.ValidationError) as refused:
			api.delete_connection(self.connection, self.connection)
		self.assertIn(self.spec, str(refused.exception))
		self.assertTrue(self.exists())
		self.assertEqual(api.delete_impact(self.connection)["logs"], 2)

	def test_delete_takes_the_log_and_the_links(self):
		frappe.delete_doc(api.SPEC, self.spec)
		# the name is typed, and it is not syncing or about to
		with self.assertRaises(frappe.ValidationError):
			api.delete_connection(self.connection, "ES Something Else")
		with scheduler.holding_sync_lock(self.connection), self.assertRaises(frappe.ValidationError):
			api.delete_connection(self.connection, self.connection)
		with (
			patch.object(api, "is_job_enqueued", return_value=True),
			self.assertRaises(frappe.ValidationError),
		):
			api.delete_connection(self.connection, self.connection)
		self.assertTrue(self.exists())
		self.assertEqual(frappe.db.count(api.PULL_LOG, {"sync_connection": self.connection}), 2)
		modified = frappe.db.get_value("ToDo", self.linked.name, "modified")

		self.assertEqual(api.delete_connection(self.connection, self.connection), {"deleted": True})
		self.assertFalse(self.exists())
		self.assertEqual(frappe.db.count(api.PULL_LOG, {"sync_connection": self.connection}), 0)
		self.assertEqual(frappe.db.count(api.SYNC_ID, {"sync_connection": self.connection}), 0)
		# the document stays, as it was
		self.assertEqual(frappe.db.get_value("ToDo", self.linked.name, "modified"), modified)
		self.assertFalse(scheduler.sync_lock(self.connection).locked())
