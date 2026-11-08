# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

import datetime
import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from espresso_sync import scheduler
from espresso_sync.espresso_sync.doctype.espresso_sync_connection import espresso_sync_connection as esc

PREFIX = "ES Schedule "


def make_scheduled_connection(name, sync_frequency, enabled=1, cron_rule=None, last_pull=None):
	name = PREFIX + name
	if frappe.db.exists(scheduler.CONNECTION, name):
		frappe.delete_doc(scheduler.CONNECTION, name, force=True)
	frappe.get_doc(
		{
			"doctype": scheduler.CONNECTION,
			"connection_name": name,
			"auth_type": "Header-based",
			"api_key": "X-Api-Key",
			"api_secret": "schedule-test-key",
			"server_url": "https://api.example.invalid/v1",
			"enabled": enabled,
			"sync_frequency": sync_frequency,
			"cron_rule": cron_rule,
			"shots": [],
		}
	).insert(ignore_permissions=True)
	if last_pull:
		frappe.db.set_value(scheduler.CONNECTION, name, "last_pull", last_pull, update_modified=False)
	return name


class TestScheduler(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		# only this test's Connections are enabled
		frappe.db.set_value(scheduler.CONNECTION, {"name": ("not like", f"{PREFIX}%")}, "enabled", 0)
		cls.now = datetime.datetime(2026, 1, 15, 12, 16)
		cls.names = {
			frequency: make_scheduled_connection(frequency, frequency)
			for frequency in ("Every Minute", "Hourly", "Daily", "Weekly", "Monthly")
		}
		cls.disabled = make_scheduled_connection("disabled hourly", "Hourly", enabled=0)
		cls.manual = make_scheduled_connection("manual", "Manual")
		cls.cron_due = make_scheduled_connection(
			"cron due", "Cron", cron_rule="*/15 * * * *", last_pull=datetime.datetime(2026, 1, 15, 11, 59)
		)
		cls.cron_not_due = make_scheduled_connection(
			"cron not due",
			"Cron",
			cron_rule="*/15 * * * *",
			last_pull=datetime.datetime(2026, 1, 15, 12, 15, 30),
		)

	def setUp(self):
		super().setUp()
		# run_connection_sync commits the attempt; these tests leave nothing behind
		commit = patch.object(frappe.local.db, "commit")
		commit.start()
		self.addCleanup(commit.stop)

	def test_every_event_enqueues_its_frequency(self):
		events = {
			"all": (scheduler.sync_all, "Every Minute"),
			"hourly": (scheduler.sync_hourly, "Hourly"),
			"daily": (scheduler.sync_daily, "Daily"),
			"weekly": (scheduler.sync_weekly, "Weekly"),
			"monthly": (scheduler.sync_monthly, "Monthly"),
		}
		hooks = frappe.get_hooks("scheduler_events", app_name="espresso_sync")
		for event, (wrapper, frequency) in events.items():
			with self.subTest(event=event), patch.object(frappe, "enqueue") as enqueue:
				self.assertEqual(hooks[event], [f"espresso_sync.scheduler.{wrapper.__name__}"])
				wrapper()
				self.assertEqual(
					[c.kwargs["connection"] for c in enqueue.call_args_list], [self.names[frequency]]
				)
		self.assertEqual(hooks["cron"], {"* * * * *": ["espresso_sync.scheduler.sync_cron"]})

	def test_one_job_per_connection(self):
		with patch.object(frappe, "enqueue") as enqueue:
			self.assertEqual(scheduler.process_sync_connections("hourly"), [self.names["Hourly"]])
		[call] = enqueue.call_args_list
		self.assertEqual(call.args, ("espresso_sync.scheduler.run_connection_sync",))
		self.assertEqual(
			{key: call.kwargs[key] for key in ("queue", "job_id", "deduplicate", "connection")},
			{
				"queue": "long",
				"job_id": f"espresso_sync:sync:{self.names['Hourly']}",
				"deduplicate": True,
				"connection": self.names["Hourly"],
			},
		)

	def test_cron(self):
		self.assertEqual(scheduler.connections_due("cron", self.now), [self.cron_due])
		with (
			patch.object(frappe, "enqueue") as enqueue,
			patch.object(scheduler, "now_datetime", return_value=self.now),
		):
			scheduler.sync_cron()
		self.assertEqual([c.kwargs["connection"] for c in enqueue.call_args_list], [self.cron_due])

	def test_cron_is_due(self):
		since = datetime.datetime(2026, 1, 15, 12, 0, 30)
		self.assertTrue(scheduler.cron_is_due("*/15 * * * *", since, datetime.datetime(2026, 1, 15, 12, 15)))
		self.assertFalse(scheduler.cron_is_due("*/15 * * * *", since, datetime.datetime(2026, 1, 15, 12, 14)))
		self.assertFalse(scheduler.cron_is_due("not a rule", since, self.now))
		self.assertFalse(scheduler.cron_is_due(None, since, self.now))

	def test_a_running_sync_is_not_started_again(self):
		name = self.names["Hourly"]
		lock = scheduler.sync_lock(name)
		with patch.object(esc.EspressoSyncConnection, "sync") as sync:
			self.assertTrue(lock.acquire(blocking=False))
			try:
				self.assertFalse(scheduler.run_connection_sync(name))
			finally:
				lock.release()
			sync.assert_not_called()
			# free again: it runs, and releases the lock
			self.assertTrue(scheduler.run_connection_sync(name))
			self.assertTrue(scheduler.run_connection_sync(name))
		self.assertEqual(sync.call_count, 2)

	def test_a_disabled_connection_is_not_synced(self):
		with patch.object(esc.EspressoSyncConnection, "sync") as sync:
			self.assertFalse(scheduler.run_connection_sync(self.disabled))
		sync.assert_not_called()

	def test_sync_now_is_refused_while_a_sync_runs(self):
		name = self.names["Hourly"]
		doc = json.dumps({"name": name})
		lock = scheduler.sync_lock(name)
		with patch.object(esc.EspressoSyncConnection, "sync") as sync:
			self.assertTrue(lock.acquire(blocking=False))
			try:
				with self.assertRaises(frappe.ValidationError):
					esc.sync_action(doc)
			finally:
				lock.release()
			sync.assert_not_called()
			# free again: it runs, and releases the lock for the scheduled job
			self.assertEqual(esc.sync_action(doc).name, name)
			self.assertEqual(sync.call_count, 1)
			self.assertTrue(scheduler.run_connection_sync(name))
		# and the other way round: the scheduled job does not run while Sync Now syncs
		with patch.object(
			esc.EspressoSyncConnection,
			"sync",
			side_effect=lambda: self.assertFalse(scheduler.run_connection_sync(name)),
		):
			esc.sync_action(doc)

	def test_a_failed_cron_sync_waits_for_its_next_time(self):
		name = make_scheduled_connection(
			"cron failing",
			"Cron",
			cron_rule="0 3 * * *",
			last_pull=datetime.datetime(2026, 1, 14, 3, 0, 5),
		)
		self.addCleanup(frappe.delete_doc, scheduler.CONNECTION, name, force=True)
		at_three = datetime.datetime(2026, 1, 15, 3, 0, 10)
		self.assertIn(name, scheduler.connections_due("cron", at_three))
		with (
			patch.object(scheduler, "now_datetime", return_value=at_three),
			patch.object(esc.EspressoSyncConnection, "sync", side_effect=RuntimeError("no API secret")),
			self.assertRaises(RuntimeError),
		):
			scheduler.run_connection_sync(name)
		self.assertEqual(
			frappe.db.get_value(scheduler.CONNECTION, name, "last_pull"),
			datetime.datetime(2026, 1, 14, 3, 0, 5),
		)
		# not at the next tick, nor for the rest of the day
		for now in (datetime.datetime(2026, 1, 15, 3, 4), datetime.datetime(2026, 1, 16, 2, 59)):
			self.assertNotIn(name, scheduler.connections_due("cron", now))
		self.assertIn(name, scheduler.connections_due("cron", datetime.datetime(2026, 1, 16, 3, 0)))

	def test_last_run(self):
		creation = datetime.datetime(2026, 1, 1)
		earlier, later = datetime.datetime(2026, 1, 2), datetime.datetime(2026, 1, 3)
		row = frappe._dict(creation=creation, last_pull=None, last_sync_attempt=None)
		self.assertEqual(scheduler.last_run(row), creation)
		self.assertEqual(
			scheduler.last_run(frappe._dict(row, last_pull=earlier, last_sync_attempt=later)), later
		)
		self.assertEqual(
			scheduler.last_run(frappe._dict(row, last_pull=later, last_sync_attempt=earlier)), later
		)
