# Copyright (c) 2023, Avunu LLC and Contributors
# See license.txt

import datetime
import inspect
import json
from unittest.mock import patch

import frappe
import frappe.client
import requests
import responses
from frappe.share import add as share_doc
from frappe.tests import IntegrationTestCase

from espresso_sync.espresso_sync.doctype.espresso_sync_connection import espresso_sync_connection as esc
from espresso_sync.sync import Run
from espresso_sync.tests.egress import make_response, public_dns
from espresso_sync.tests.test_sync import (
	EXPORT_TASKS,
	IMPORT_TASKS,
	make_spec,
	make_transform,
)
from espresso_sync.utils import safe_fetch
from espresso_sync.utils.safe_fetch import REQUEST_TIMEOUT, RateLimitedSession

WEBSITE_USER = "es-website-user@example.com"
DESK_USER = "es-desk-user@example.com"
MANAGER_USER = "es-manager@example.com"
DESK_ROLE = "Espresso Sync Test Desk Role"
API = "https://api.example.invalid/v1"


def make_user(email, roles=()):
	if frappe.db.exists("User", email):
		return frappe.get_doc("User", email)
	return frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": email.split("@")[0],
			"send_welcome_email": 0,
			"roles": [{"role": role} for role in roles],
		}
	).insert(ignore_permissions=True)


def make_connection(
	name="ES Permission Test",
	auth_type="Basic",
	api_key="sync-user",
	secret="hunter2-secret-value",
	**values,
):
	if frappe.db.exists("Espresso Sync Connection", name):
		frappe.delete_doc("Espresso Sync Connection", name, force=True)
	connection = frappe.get_doc(
		{
			"doctype": "Espresso Sync Connection",
			"connection_name": name,
			"auth_type": auth_type,
			"api_key": api_key,
			"api_secret": secret,
			"server_url": API,
			"sync_frequency": "Manual",
			**values,
		}
	).insert(ignore_permissions=True)
	return esc.get_connection(str(connection.name))


class TestEspressoSyncConnection(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("Role", DESK_ROLE):
			frappe.get_doc({"doctype": "Role", "role_name": DESK_ROLE, "desk_access": 1}).insert(
				ignore_permissions=True
			)
		make_user(WEBSITE_USER)
		make_user(DESK_USER, [DESK_ROLE])
		make_user(MANAGER_USER, ["System Manager"])

	def setUp(self):
		self.enterContext(public_dns())
		frappe.set_user("Administrator")
		self.connection = make_connection()
		# a System Manager could share the Connection with someone; that must not
		# be enough to sync it, or to change where its credentials go
		share_doc("Espresso Sync Connection", self.connection.name, DESK_USER, read=1, write=1, notify=0)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_sync_now_is_the_only_endpoint(self):
		whitelisted = {
			name for name, fn in inspect.getmembers(esc, inspect.isfunction) if fn in frappe.whitelisted
		} | {name for name, fn in vars(esc.EspressoSyncConnection).items() if fn in frappe.whitelisted}
		self.assertEqual(whitelisted, {"sync_action"})

	def test_sync_now_is_for_system_managers(self):
		doc = json.dumps({"name": self.connection.name})
		with patch.object(esc.EspressoSyncConnection, "sync", return_value=0) as sync:
			for user in (WEBSITE_USER, DESK_USER):
				frappe.set_user(user)
				with self.subTest(user=user), self.assertRaises(frappe.PermissionError):
					esc.sync_action(doc)
			sync.assert_not_called()
			frappe.set_user(MANAGER_USER)
			self.assertEqual(esc.sync_action(doc).name, self.connection.name)
			sync.assert_called_once()

	def test_sync_now_reports_failures(self):
		frappe.clear_messages()
		with patch.object(esc.EspressoSyncConnection, "sync", return_value=2):
			esc.sync_now(self.connection.name)
		self.assertIn("2 failed", json.dumps(frappe.local.message_log))

	def test_a_share_cannot_move_the_credentials(self):
		doc = frappe.get_doc("Espresso Sync Connection", self.connection.name).as_dict()
		doc["server_url"] = "https://attacker.example.invalid"
		doc["allowed_host"] = "attacker.example.invalid"
		frappe.set_user(DESK_USER)
		self.assertTrue(frappe.has_permission("Espresso Sync Connection", "write", self.connection.name))
		with self.assertRaises(frappe.PermissionError):
			frappe.client.save(doc)
		frappe.set_user("Administrator")
		self.assertEqual(
			frappe.db.get_value("Espresso Sync Connection", self.connection.name, "server_url"), API
		)

		frappe.set_user(MANAGER_USER)
		frappe.client.save(doc)
		self.assertEqual(
			frappe.db.get_value("Espresso Sync Connection", self.connection.name, "allowed_host"),
			"attacker.example.invalid",
		)

	def test_the_server_url_and_the_allowed_host(self):
		self.assertEqual(self.connection.allowed_host, "api.example.invalid")
		for server_url, allowed_host in (
			("api.example.invalid/v1", ""),
			("ftp://api.example.invalid", ""),
			(API, "https://api.example.invalid/x"),
			(API, "other.example.invalid"),
			(API, "api.example.invalid:8443"),
		):
			connection = esc.get_connection(self.connection.name)
			connection.server_url, connection.allowed_host = server_url, allowed_host
			with self.subTest(server_url=server_url, allowed_host=allowed_host):
				self.assertRaises(frappe.ValidationError, connection.save)
		connection = esc.get_connection(self.connection.name)
		connection.server_url, connection.allowed_host = "https://API.example.invalid/v2", ""
		connection.save()
		self.assertEqual(connection.allowed_host, "api.example.invalid")

	def test_a_cron_frequency_needs_a_valid_rule(self):
		for cron_rule, valid in (("", False), ("every tuesday", False), ("*/15 * * * *", True)):
			connection = esc.get_connection(self.connection.name)
			connection.sync_frequency = "Cron"
			connection.cron_rule = cron_rule
			with self.subTest(cron_rule=cron_rule):
				if valid:
					connection.save()
				else:
					self.assertRaises(frappe.ValidationError, connection.save)

	def test_credential_headers(self):
		self.assertEqual(
			self.connection.get_credential_headers(),
			{"Authorization": "Basic c3luYy11c2VyOmh1bnRlcjItc2VjcmV0LXZhbHVl"},
		)
		connection = make_connection("ES Header Auth", auth_type="Header-based", api_key="X-Key", secret="k")
		self.assertEqual(connection.get_credential_headers(), {"X-Key": "k"})
		connection.api_key = None
		self.assertEqual(connection.get_credential_headers(), {})

	def test_a_pull_log_that_cannot_be_saved_does_not_log_the_credentials(self):
		run = Run(self.connection)
		encoded = self.connection.get_credential_headers()["Authorization"].split()[1]
		# a link that does not exist fails insert() before the Pull Log validates
		run.log(sync_doctype="ToDo", sync_doc="does-not-exist", response=json.dumps({"echo": encoded}))
		error = frappe.get_all(
			"Error Log",
			filters={"method": "Error saving pull log"},
			fields=["error"],
			order_by="creation desc",
			limit=1,
		)[0].error
		self.assertIn(self.connection.name, error)
		self.assertNotIn(encoded, error)
		self.assertNotIn("hunter2-secret-value", error)


class TestShots(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.enterContext(public_dns())
		frappe.set_user("Administrator")
		self.connection = make_connection("ES Shot Test", auth_type="Header-based", api_key="X-Api-Key")
		self.spec = make_spec(self.connection.name)
		self.import_transform = make_transform("ES Shot Import", self.spec, **IMPORT_TASKS)
		self.export_transform = make_transform("ES Shot Export", self.spec, **EXPORT_TASKS)

	def save_shot(self, **shot):
		connection = esc.get_connection(self.connection.name)
		connection.set("shots", [shot])
		connection.save()
		return connection

	def test_a_shot_runs_active_transforms_of_its_doctype_on_its_connection(self):
		connection = self.save_shot(
			dt="ToDo",
			do_import=1,
			import_transform=self.import_transform,
			do_export=1,
			export_transform=self.export_transform,
		)
		connection.enabled = 1
		connection.save()
		self.assertTrue(frappe.db.exists("Custom Field", {"dt": "ToDo", "fieldname": "espresso_sync_ids"}))

		other = make_connection("ES Shot Other")
		other_spec = make_spec(other.name)
		for shot in (
			{"dt": "ToDo", "do_import": 1},
			{"dt": "ToDo", "do_export": 1},
			{"dt": "ToDo", "do_import": 1, "import_transform": self.export_transform},
			{"dt": "ToDo", "do_export": 1, "export_transform": self.import_transform},
			{"dt": "Note", "do_import": 1, "import_transform": self.import_transform},
			{
				"dt": "ToDo",
				"do_import": 1,
				"import_transform": make_transform(
					"ES Shot Draft", self.spec, activate=False, **IMPORT_TASKS
				),
			},
			{
				"dt": "ToDo",
				"do_import": 1,
				"import_transform": make_transform("ES Shot Elsewhere", other_spec, **IMPORT_TASKS),
			},
		):
			with self.subTest(shot=shot), self.assertRaises(frappe.ValidationError):
				self.save_shot(**shot)


class TestRetry(IntegrationTestCase):
	"""429 Too Many Requests: waited for and retried, a bounded number of times."""

	URL = f"{API}/limited"

	def setUp(self):
		super().setUp()
		self.enterContext(public_dns())

	def send(self, *statuses_and_headers):
		session = RateLimitedSession()
		with (
			responses.RequestsMock(assert_all_requests_are_fired=False) as rsps,
			patch.object(safe_fetch.time, "sleep") as sleep,
		):
			for status, headers in statuses_and_headers:
				rsps.add(responses.GET, self.URL, json={"status": status}, status=status, headers=headers)
			response = session.request("GET", self.URL)
			calls = len(rsps.calls)
		return response, calls, [c.args[0] for c in sleep.call_args_list]

	def test_retry_after_seconds(self):
		response, calls, waits = self.send((429, {"Retry-After": "2"}), (200, {}))
		self.assertEqual((response.status_code, calls, waits), (200, 2, [2.0]))

	def test_retry_after_date_and_backoff(self):
		soon = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=30)
		response, calls, waits = self.send(
			(429, {"Retry-After": soon.strftime("%a, %d %b %Y %H:%M:%S GMT")}), (429, {}), (200, {})
		)
		self.assertEqual((response.status_code, calls), (200, 3))
		self.assertTrue(25 <= waits[0] <= 30, waits)
		# no Retry-After: the default backoff, doubled for the second retry
		self.assertEqual(waits[1], safe_fetch.DEFAULT_BACKOFF * 2)

	def test_retries_are_bounded(self):
		response, calls, waits = self.send((429, {"Retry-After": "1"}))
		self.assertEqual(response.status_code, 429)
		self.assertEqual(calls, 1 + safe_fetch.MAX_RETRIES)
		self.assertEqual(len(waits), safe_fetch.MAX_RETRIES)

	def test_a_long_retry_after_is_not_waited_for(self):
		response, calls, waits = self.send((429, {"Retry-After": "3600"}), (200, {}))
		self.assertEqual((response.status_code, calls, waits), (429, 1, []))

	def test_the_rate_limit(self):
		session = RateLimitedSession(2)
		with (
			patch.object(requests.Session, "request", return_value=make_response({})) as request,
			patch.object(safe_fetch.time, "sleep") as sleep,
		):
			for _ in range(3):
				session.request("GET", self.URL)
		self.assertEqual(request.call_count, 3)
		sleep.assert_called_once()
		self.assertEqual(request.call_args_list[0].kwargs["timeout"], REQUEST_TIMEOUT)
