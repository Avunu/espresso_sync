# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""The portal's Sync log endpoints: failure groups, daily activity, retention, clearing."""

import inspect
import json
from typing import Any, cast

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, getdate, now_datetime

from espresso_sync.api import logs as api

CONNECTION = "Espresso Sync Connection"
PULL_LOG = "Espresso Sync Pull Log"
SHOP = "ES Logs API Test Shop"
OTHER = "ES Logs API Test Other"
MANAGER = "es-logs-manager@example.com"
OUTSIDER = "es-logs-outsider@example.com"
READS = ("failure_groups", "activity", "get_retention")
WRITES = ("set_retention", "clear_logs")


def make_user(email: str, roles: list[str]) -> str:
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


def make_connection(name: str) -> str:
	if not frappe.db.exists(CONNECTION, name):
		frappe.get_doc(
			{
				"doctype": CONNECTION,
				"connection_name": name,
				"auth_type": "Header-based",
				"api_key": "X-Api-Key",
				"api_secret": "logs-api-secret",
				"server_url": "https://api.example.invalid/v1",
				"sync_frequency": "Manual",
			}
		).insert(ignore_permissions=True)
	return name


def make_log(connection: str, status: str = "Failure", code: str = "http-status", **values) -> str:
	"""A Pull Log entry of `connection`; `creation` puts it at another time than now."""
	creation = values.pop("creation", None)
	doc = frappe.get_doc(
		{
			"doctype": PULL_LOG,
			"sync_connection": connection,
			"sync_doctype": "ToDo",
			"sync_direction": "Import",
			"sync_status": status,
			"request_type": "GET",
			"diagnostics": json.dumps(
				[
					{"severity": "warning", "code": "schema", "message": "not the last error"},
					{"severity": "error", "code": code, "message": f"{code} went wrong"},
				]
			)
			if status == "Failure"
			else None,
			**values,
		}
	)
	# the documents and transforms the entries name are not made
	doc.flags.ignore_links = True
	doc.insert()
	if creation:
		frappe.db.set_value(PULL_LOG, doc.name, "creation", creation, update_modified=False)
	return str(doc.name)


class TestLogsEndpoints(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		make_user(MANAGER, ["System Manager"])
		make_user(OUTSIDER, ["Website Manager"])
		make_connection(SHOP)
		make_connection(OTHER)

	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.db.delete(PULL_LOG, {"sync_connection": ("in", (SHOP, OTHER))})
		self.now = cast("Any", now_datetime())
		for connection in (SHOP, OTHER):
			frappe.db.set_value(CONNECTION, connection, "last_sync_attempt", None, update_modified=False)
		frappe.set_user(MANAGER)

	def attempt(self, connection: str, **ago):
		"""`connection` last synced that long ago."""
		frappe.db.set_value(
			CONNECTION,
			connection,
			"last_sync_attempt",
			add_to_date(self.now, **{unit: -value for unit, value in ago.items()}),
			update_modified=False,
		)

	def ago(self, **ago):
		return add_to_date(self.now, **{unit: -value for unit, value in ago.items()})

	def groups(self, **kwargs) -> dict[tuple[str, str], dict[str, Any]]:
		"""The failure groups of the two test Connections, by (connection, code)."""
		return {
			(group["connection"], group["code"]): group
			for group in api.failure_groups(**kwargs)["groups"]
			if group["connection"] in (SHOP, OTHER)
		}

	def count(self, connection: str, **filters) -> int:
		return frappe.db.count(PULL_LOG, {"sync_connection": connection, **filters})

	def test_only_these_are_whitelisted_and_writes_are_post_only(self):
		whitelisted = {
			name for name, fn in inspect.getmembers(api, inspect.isfunction) if fn in frappe.whitelisted
		}
		self.assertEqual(whitelisted, {*READS, *WRITES})
		for name in WRITES:
			self.assertEqual(
				frappe.allowed_http_methods_for_whitelisted_func[getattr(api, name)], ["POST"], name
			)

	def test_only_a_system_manager_may_call_any_of_them(self):
		make_log(SHOP)
		frappe.set_user(OUTSIDER)
		calls = {
			"failure_groups": lambda: api.failure_groups(SHOP),
			"activity": lambda: api.activity(SHOP),
			"get_retention": api.get_retention,
			"set_retention": lambda: api.set_retention(10),
			"clear_logs": lambda: api.clear_logs(connection=SHOP),
		}
		self.assertEqual(set(calls), {*READS, *WRITES})
		for name, call in calls.items():
			with self.subTest(endpoint=name), self.assertRaises(frappe.PermissionError):
				call()
		self.assertEqual(self.count(SHOP), 1)

	def test_failures_are_grouped_since_each_connections_last_attempt(self):
		self.attempt(SHOP, hours=1)
		# before the last sync: not what is failing now
		make_log(SHOP, creation=self.ago(hours=3))
		make_log(SHOP, creation=self.ago(hours=2))
		make_log(SHOP, creation=self.ago(minutes=30))
		make_log(SHOP, creation=self.ago(minutes=20))
		newest = make_log(SHOP, creation=self.ago(minutes=10))
		make_log(SHOP, code="conflict", creation=self.ago(minutes=5))
		make_log(SHOP, status="Success", creation=self.ago(minutes=5))
		# never attempted: every failure it has
		make_log(OTHER, creation=self.ago(days=20))

		groups = self.groups()

		self.assertEqual(set(groups), {(SHOP, "http-status"), (SHOP, "conflict"), (OTHER, "http-status")})
		group = groups[SHOP, "http-status"]
		self.assertEqual(group["count"], 3)
		self.assertEqual(group["latest_log"], newest)
		self.assertEqual(group["latest"], str(frappe.db.get_value(PULL_LOG, newest, "creation")))
		# the last error of the entry, not the warning before it
		self.assertEqual(group["message"], "http-status went wrong")
		self.assertEqual((group["doctype"], group["direction"], group["transform"]), ("ToDo", "Import", None))
		self.assertEqual(groups[SHOP, "conflict"]["count"], 1)
		self.assertEqual(groups[OTHER, "http-status"]["count"], 1)

		# one Connection's only
		self.assertEqual(set(self.groups(connection=SHOP)), {(SHOP, "http-status"), (SHOP, "conflict")})
		# the most frequent group first
		ordered = api.failure_groups(connection=SHOP)
		self.assertEqual([group["count"] for group in ordered["groups"]], [3, 1])
		self.assertFalse(ordered["truncated"])

	def test_since_replaces_the_last_attempt_as_the_cutoff(self):
		self.attempt(SHOP, hours=1)
		make_log(SHOP, creation=self.ago(days=3))
		make_log(SHOP, creation=self.ago(hours=2))
		make_log(SHOP, creation=self.ago(minutes=30))
		make_log(OTHER, creation=self.ago(days=20))

		self.assertEqual(self.groups(since="attempt")[SHOP, "http-status"]["count"], 1)
		self.assertNotIn((SHOP, "http-status"), self.groups(since="1h", connection=OTHER))
		self.assertEqual(self.groups(since="24h")[SHOP, "http-status"]["count"], 2)
		week = self.groups(since="7d")
		self.assertEqual(week[SHOP, "http-status"]["count"], 3)
		self.assertNotIn((OTHER, "http-status"), week)
		# a date, or a time, as well as a period
		self.assertEqual(self.groups(since=str(getdate(self.ago(days=30))))[OTHER, "http-status"]["count"], 1)
		self.assertEqual(
			self.groups(since=str(self.ago(hours=3)), connection=SHOP)[SHOP, "http-status"]["count"], 2
		)
		with self.assertRaises(frappe.ValidationError):
			api.failure_groups(since="last tuesday-ish")

	def test_an_entry_without_an_error_diagnostic_is_grouped_as_unknown(self):
		make_log(SHOP, diagnostics=None)
		# the column takes only JSON, but not only a list of diagnostics
		make_log(SHOP, diagnostics=json.dumps({"code": "not-a-list"}))
		make_log(SHOP, diagnostics=json.dumps([{"severity": "warning", "code": "schema", "message": "odd"}]))

		groups = self.groups(connection=SHOP)

		# a warning is not what an entry failed with: the Sync log's code filter reads the same
		self.assertEqual(groups[SHOP, "unknown"]["count"], 3)
		self.assertNotIn((SHOP, "schema"), groups)
		self.assertEqual(api.last_error("not json")[0], "unknown")
		error = {"severity": "error", "code": "http-status", "message": "HTTP 500"}
		for unnamed in ({"severity": "error", "message": "no code"}, {"severity": "error", "code": 5}):
			with self.subTest(unnamed=unnamed):
				self.assertEqual(api.last_error([error, unnamed]), ("http-status", "HTTP 500"))
		self.assertEqual(api.last_error([{"severity": "error", "code": "x", "message": 5}]), ("x", ""))

	def test_failure_groups_reads_no_more_than_the_limit(self):
		for minutes in range(4):
			make_log(SHOP, code=f"code-{minutes}", creation=self.ago(minutes=minutes))

		found = api.failure_groups(connection=SHOP, limit=2)

		self.assertTrue(found["truncated"])
		# the newest two
		self.assertEqual({group["code"] for group in found["groups"]}, {"code-0", "code-1"})
		self.assertFalse(api.failure_groups(connection=SHOP, limit=4)["truncated"])
		# a limit below one reads one, and one above the cap is the cap
		self.assertEqual(len(api.failure_groups(connection=SHOP, limit=0)["groups"]), 1)
		self.assertEqual(len(api.failure_groups(connection=SHOP, limit=10**6)["groups"]), 4)

	def test_failure_groups_of_a_missing_connection_is_refused(self):
		with self.assertRaises(frappe.DoesNotExistError):
			api.failure_groups(connection="ES Logs API No Such Shop")

	def test_activity_counts_each_day_and_fills_the_empty_ones(self):
		today = getdate(self.now)
		yesterday = add_to_date(today, days=-1)
		make_log(SHOP, status="Success", sync_doc="todo-1")
		make_log(SHOP, status="Success", sync_doc="todo-2")
		make_log(SHOP, status="Success", sync_doc="todo-3", sync_direction="Export")
		# a request: it counts only when it failed
		make_log(SHOP, status="Success")
		make_log(SHOP, status="Failure")
		make_log(SHOP, status="Failure", sync_doc="todo-4", creation=f"{yesterday} 12:00:00")
		# out of the days asked for, and another Connection's
		make_log(SHOP, status="Failure", creation=f"{add_to_date(today, days=-3)} 12:00:00")
		make_log(OTHER, status="Success", sync_doc="todo-5")

		self.assertEqual(
			api.activity(SHOP, days=3),
			[
				{"date": str(add_to_date(today, days=-2)), "imported": 0, "exported": 0, "failed": 0},
				{"date": str(yesterday), "imported": 0, "exported": 0, "failed": 1},
				{"date": str(today), "imported": 2, "exported": 1, "failed": 1},
			],
		)
		# every Connection's: at least these
		everything = api.activity()
		self.assertEqual(len(everything), 7)
		self.assertGreaterEqual(everything[-1]["imported"], 3)
		self.assertGreaterEqual(sum(day["failed"] for day in everything), 3)

	def test_activity_days_are_kept_between_one_and_thirty(self):
		self.assertEqual(len(api.activity(SHOP, days=0)), 1)
		self.assertEqual(len(api.activity(SHOP, days=400)), 30)
		with self.assertRaises(frappe.DoesNotExistError):
			api.activity("ES Logs API No Such Shop")

	def test_retention_starts_at_the_hooks_default(self):
		frappe.db.delete(api.LOGS_TO_CLEAR, {"parent": api.LOG_SETTINGS, "ref_doctype": PULL_LOG})
		self.assertEqual(api.default_retention(), 30)
		self.assertEqual(api.get_retention(), {"days": 30})

	def test_retention_is_the_log_settings_row(self):
		before = len(frappe.local.message_log)
		self.assertEqual(api.set_retention(45), {"days": 45})
		self.assertEqual(api.get_retention(), {"days": 45})

		settings = cast("Any", frappe.get_doc(api.LOG_SETTINGS))
		rows = {row.ref_doctype: row.days for row in settings.logs_to_clear}
		self.assertEqual(rows[PULL_LOG], 45)
		# changed again in place: one row, and the other logs' rows are still there
		self.assertEqual(api.set_retention(90), {"days": 90})
		settings.reload()
		self.assertEqual([row.days for row in settings.logs_to_clear if row.ref_doctype == PULL_LOG], [90])
		self.assertEqual({row.ref_doctype for row in settings.logs_to_clear}, set(rows))
		# Log Settings' own announcements are not the caller's
		self.assertEqual(len(frappe.local.message_log), before)

	def test_retention_is_added_when_log_settings_has_no_row(self):
		frappe.db.delete(api.LOGS_TO_CLEAR, {"parent": api.LOG_SETTINGS, "ref_doctype": PULL_LOG})
		self.assertEqual(api.set_retention(7), {"days": 7})
		self.assertEqual(api.stored_retention(), 7)

	def test_retention_is_between_one_day_and_ten_years(self):
		api.set_retention(45)
		for days in (0, -1, 3651):
			with self.subTest(days=days), self.assertRaises(frappe.ValidationError):
				api.set_retention(days)
		self.assertEqual(api.get_retention(), {"days": 45})
		self.assertEqual(api.set_retention(1), {"days": 1})
		self.assertEqual(api.set_retention(3650), {"days": 3650})

	def test_clear_logs_of_a_connection_leaves_the_others(self):
		make_log(SHOP)
		make_log(SHOP, status="Success")
		make_log(OTHER)

		self.assertEqual(api.clear_logs(connection=SHOP), {"deleted": 2})

		self.assertEqual(self.count(SHOP), 0)
		self.assertEqual(self.count(OTHER), 1)
		self.assertEqual(api.clear_logs(connection=SHOP), {"deleted": 0})

	def test_clear_logs_takes_only_what_the_filters_match(self):
		make_log(SHOP, creation=self.ago(days=10))
		make_log(SHOP, status="Success", creation=self.ago(days=10))
		make_log(SHOP, status="Success", sync_direction="Export", sync_doctype="Contact")
		make_log(SHOP, status="Success", transform="ES Logs API Transform")
		recent = make_log(SHOP)

		self.assertEqual(
			api.clear_logs(
				connection=SHOP, filters={"sync_status": "Failure", "before": str(self.ago(days=1))}
			),
			{"deleted": 1},
		)
		self.assertTrue(frappe.db.exists(PULL_LOG, recent))
		# as the request sends them: JSON, and the empty ones are not filters
		self.assertEqual(
			api.clear_logs(
				connection=SHOP,
				filters=json.dumps({"sync_direction": "Export", "sync_doctype": "Contact", "transform": ""}),
			),
			{"deleted": 1},
		)
		self.assertEqual(
			api.clear_logs(connection=SHOP, filters={"transform": "ES Logs API Transform"}), {"deleted": 1}
		)
		self.assertEqual(self.count(SHOP), 2)

	def test_clear_logs_by_filters_alone_covers_every_connection(self):
		make_log(SHOP, sync_doctype="Contact")
		make_log(OTHER, sync_doctype="Contact")
		kept = make_log(OTHER)

		deleted = api.clear_logs(filters={"sync_doctype": "Contact"})["deleted"]

		self.assertGreaterEqual(deleted, 2)
		self.assertEqual(self.count(SHOP), 0)
		self.assertEqual(frappe.get_all(PULL_LOG, filters={"sync_connection": OTHER}, pluck="name"), [kept])

	def test_clear_logs_refuses_filters_it_does_not_know(self):
		make_log(SHOP)
		refused: tuple[Any, ...] = (
			{"sync_doc": "todo-1"},
			{"name": ("like", "%")},
			{"sync_status": "Success", "owner": "Administrator"},
			{"sync_status": "Anything"},
			{"sync_direction": ["in", ["Import", "Export"]]},
			{"sync_doctype": ("like", "%")},
			{"before": "not a time"},
			'["sync_status"]',
			"not json",
		)
		for filters in refused:
			with self.subTest(filters=filters), self.assertRaises(frappe.ValidationError):
				api.clear_logs(connection=SHOP, filters=filters)
		self.assertEqual(self.count(SHOP), 1)

	def test_clear_logs_of_everything_needs_the_confirmation(self):
		make_log(SHOP)
		make_log(OTHER)
		for kwargs in ({}, {"confirm": "yes"}, {"filters": {}}, {"filters": {"sync_status": ""}}):
			with self.subTest(kwargs=kwargs), self.assertRaises(frappe.ValidationError):
				api.clear_logs(**kwargs)
		self.assertEqual(self.count(SHOP) + self.count(OTHER), 2)

		everything = frappe.db.count(PULL_LOG)
		self.assertEqual(api.clear_logs(confirm="all"), {"deleted": everything})
		self.assertEqual(frappe.db.count(PULL_LOG), 0)

	def test_clear_logs_of_a_missing_connection_is_refused(self):
		make_log(SHOP)
		with self.assertRaises(frappe.DoesNotExistError):
			api.clear_logs(connection="ES Logs API No Such Shop")
		self.assertEqual(self.count(SHOP), 1)
