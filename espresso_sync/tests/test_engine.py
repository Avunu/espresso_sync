# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

import datetime
from decimal import Decimal
from unittest.mock import patch

import frappe
import jsonata
import jsonata.timebox
from frappe.tests import IntegrationTestCase

from espresso_sync.espresso_sync.doctype.espresso_sync_connection.espresso_sync_connection import (
	ensure_sync_fields,
)
from espresso_sync.tests.test_schema_api import make_user
from espresso_sync.transform import engine

CONNECTION = "ES Engine Test"
MANAGER_USER = "es-engine-manager@example.com"


def make_connection() -> str:
	if not frappe.db.exists("Espresso Sync Connection", CONNECTION):
		frappe.get_doc(
			{"doctype": "Espresso Sync Connection", "connection_name": CONNECTION, "sync_frequency": "Manual"}
		).insert(ignore_permissions=True)
	return CONNECTION


class TestEngine(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def test_frappe_values_are_read_as_json(self):
		data = frappe._dict(
			when=datetime.datetime(2026, 1, 15, 9, 30),
			day=datetime.date(2026, 1, 15),
			amount=Decimal("12.50"),
			lines=[frappe._dict(qty=Decimal("2"), rate=Decimal("1.25"))],
		)
		self.assertEqual(engine.evaluate("when", data), "2026-01-15 09:30:00")
		self.assertEqual(engine.evaluate("day", data), "2026-01-15")
		self.assertEqual(engine.evaluate("amount", data), 12.5)
		self.assertEqual(engine.evaluate("$sum(lines.(qty * rate))", data), 2.5)

	def test_undefined_and_null(self):
		self.assertIsNone(engine.evaluate("no_such_field", {}))
		self.assertEqual(engine.evaluate("no_such_field", {}, default="gone"), "gone")
		self.assertEqual(engine.evaluate("[a, null, b]", {"a": 1}), [1, None])
		self.assertEqual(engine.evaluate('{"a": a, "b": b}', {"a": None}), {"a": None})
		with self.assertRaises(jsonata.JException):
			engine.evaluate("lines[", {})

	def test_expressions_are_compiled_once(self):
		engine.compile_expression.cache_clear()
		for n in range(3):
			self.assertEqual(engine.evaluate("n + 1", {"n": n}), n + 1)
		info = engine.compile_expression.cache_info()
		self.assertEqual((info.misses, info.hits), (1, 2))

	def test_now_is_the_time_of_each_evaluation(self):
		engine.compile_expression.cache_clear()
		clock = [1_794_000_000_000]
		with patch.object(jsonata.timebox.Timebox, "current_milli_time", side_effect=lambda: clock[0]):
			self.assertEqual(engine.evaluate("$millis()", {}), clock[0])
			# compiled after it: jsonata-python makes this one the thread's current instance
			self.assertEqual(engine.evaluate("n", {"n": 1}), 1)
			clock[0] += 5000
			self.assertEqual(engine.evaluate("$millis()", {}), clock[0])
			self.assertEqual(engine.evaluate("$now()", {}), "2026-11-06T21:20:05.000Z")
		self.assertEqual(engine.compile_expression.cache_info().misses, 3)

	def test_a_runaway_expression_is_stopped(self):
		endless = "($f := function($n){ $n > 0 ? $f($n + 1) : 0 }; $f(1))"
		deep = "($f := function($n){ $n = 0 ? 0 : 1 + $f($n - 1) }; $f(100000))"
		with patch.object(engine, "TIMEOUT_MS", 200), self.assertRaises(jsonata.JException) as raised:
			engine.evaluate(endless, {})
		self.assertEqual(raised.exception.error, "D1012")
		with self.assertRaises(jsonata.JException) as raised:
			engine.evaluate(deep, {})
		self.assertEqual(raised.exception.error, "D1011")
		# the timebox starts with each evaluation, not when the expression was cached
		self.assertEqual(engine.evaluate("$sum(lines)", {"lines": [1, 2]}), 3)

	def test_dates_checks_and_values(self):
		frappe.db.set_single_value("System Settings", "time_zone", "America/New_York")
		self.assertEqual(engine.evaluate('$frappeDate("2026-01-15")', {}), "2026-01-15")
		self.assertEqual(
			engine.evaluate('$frappeDatetime("2026-01-15T02:30:00Z")', {}), "2026-01-14 21:30:00.000000"
		)
		self.assertEqual(engine.evaluate('$frappeDate("2026-01-15T02:30:00Z")', {}), "2026-01-14")
		self.assertEqual(
			engine.evaluate('$frappeDatetime("2026-01-15 09:30")', {}), "2026-01-15 09:30:00.000000"
		)
		self.assertIsNone(engine.evaluate("$frappeDate(nothing)", {}))
		self.assertEqual(
			engine.evaluate(
				'[$frappeCheck(true), $frappeCheck("false"), $frappeCheck("1"), $frappeCheck(0)]', {}
			),
			[1, 0, 1, 0],
		)
		with self.assertRaises(frappe.ValidationError):
			engine.evaluate('$frappeDate("not a date")', {})

		todo = frappe.get_doc({"doctype": "ToDo", "description": "engine value"}).insert()
		self.assertEqual(
			engine.evaluate('$getValue("ToDo", name, "description")', {"name": todo.name}), "engine value"
		)
		self.assertIsNone(engine.evaluate('$getValue("ToDo", "no such todo", "description")', {}))
		self.assertEqual(
			engine.evaluate('$getValue("System Settings", "System Settings", "time_zone")', {}),
			"America/New_York",
		)
		# JSONata's own $single is still there
		self.assertEqual(engine.evaluate("$single([1, 2], function($v){ $v > 1 })", {}), 2)
		with self.assertRaises(frappe.ValidationError):
			engine.evaluate('$getValue("ToDo", "x", "no_such_field")', {})

	def test_sync_ids_are_read_for_the_connection(self):
		ensure_sync_fields("ToDo")
		todo = frappe.get_doc(
			{
				"doctype": "ToDo",
				"description": "synced",
				"espresso_sync_ids": [
					{"sync_connection": make_connection(), "external_id": "ext-42"},
				],
			}
		).insert()
		self.assertEqual(engine.evaluate('$syncId("ToDo", $)', todo.name, connection=CONNECTION), "ext-42")
		self.assertEqual(
			engine.evaluate('$localName("ToDo", "ext-42")', {}, connection=CONNECTION), todo.name
		)
		# another Connection's ids are not this one's
		self.assertIsNone(engine.evaluate('$localName("ToDo", "ext-42")', {}, connection="Other"))
		self.assertIsNone(engine.evaluate('$syncId("ToDo", $)', todo.name, connection="Other"))
		# a DocType without sync ids has none
		self.assertIsNone(engine.evaluate('$localName("Note", "ext-42")', {}, connection=CONNECTION))

	def test_functions_read_as_the_session_user(self):
		frappe.set_user(make_user(MANAGER_USER, ["System Manager"]))
		# Server Script is for Script Managers
		with self.assertRaises(frappe.PermissionError):
			engine.evaluate('$getValue("Server Script", "x", "script")', {})
