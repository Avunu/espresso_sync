# Copyright (c) 2023, Avunu LLC and Contributors
# See license.txt

import datetime
import json
from unittest.mock import MagicMock, patch

import frappe
import frappe.client
import frappe.handler
import requests
import responses
from frappe.share import add as share_doc
from frappe.tests import IntegrationTestCase

from espresso_sync import requests_machine, sync_machine
from espresso_sync.espresso_sync.doctype.espresso_sync_connection import espresso_sync_connection as esc
from espresso_sync.requests_machine import REQUEST_TIMEOUT, RateLimitedSession

WEBSITE_USER = "es-website-user@example.com"
DESK_USER = "es-desk-user@example.com"
MANAGER_USER = "es-manager@example.com"
DESK_ROLE = "Espresso Sync Test Desk Role"
API = "https://api.example.invalid/v1"


def make_user(email, roles=()):
	if frappe.db.exists("User", email):
		return frappe.get_doc("User", email)
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": email.split("@")[0],
			"send_welcome_email": 0,
			"roles": [{"role": role} for role in roles],
		}
	).insert(ignore_permissions=True)
	return user


def make_connection(
	name="ES Permission Test",
	auth_type="Basic",
	api_key="sync-user",
	secret="hunter2-secret-value",
	**shot,
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
			"api_domain": "api.example.invalid",
			"api_base": "/v1",
			"sync_frequency": "Manual",
			"shots": [
				{
					"dt": "ToDo",
					"uri": "todos",
					"do_import": 0,
					"do_export": 0,
					"object_map_import": json.dumps({"description": "title"}),
					**shot,
				}
			],
		}
	).insert(ignore_permissions=True)
	# reload: the controller binds its Pull Log to the name it had when loaded
	return esc.get_connection(str(connection.name))


def fake_response(payload, status_code=200):
	response = MagicMock()
	response.status_code = status_code
	response.json.return_value = payload
	response.text = json.dumps(payload)
	return response


def pull_logs(connection_name):
	return frappe.get_all(
		"Espresso Sync Pull Log",
		filters={"sync_connection": connection_name},
		fields=["sync_doc", "sync_status", "request_type", "url", "response", "object", "diagnostics"],
		order_by="creation asc, name asc",
	)


class TestEspressoSyncConnection(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("Role", DESK_ROLE):
			frappe.get_doc({"doctype": "Role", "role_name": DESK_ROLE, "desk_access": 1}).insert(
				ignore_permissions=True
			)
		cls.users = [
			make_user(WEBSITE_USER),
			make_user(DESK_USER, [DESK_ROLE]),
			make_user(MANAGER_USER, ["System Manager"]),
		]

	def setUp(self):
		frappe.set_user("Administrator")
		self.connection = make_connection()
		self.shot_name = self.connection.shots[0].name
		# get_sample_data substitutes the URL against one existing document
		if not frappe.db.exists("ToDo", {"description": "espresso sync test"}):
			frappe.get_doc({"doctype": "ToDo", "description": "espresso sync test"}).insert(
				ignore_permissions=True
			)
		# a System Manager could share the Connection with someone; that must not
		# be enough to reach the endpoints
		share_doc("Espresso Sync Connection", self.connection.name, DESK_USER, read=1, write=1, notify=0)

	def tearDown(self):
		frappe.set_user("Administrator")

	# endpoint name -> callable invoking it the way the desk does
	def endpoints(self):
		doc_arg = json.dumps({"name": self.connection.name})

		def doc_method(method, **args):
			def call():
				# run_doc_method checks the HTTP verb of the current request
				frappe.local.request = frappe._dict(method="POST")
				try:
					return frappe.handler.run_doc_method(
						method=method,
						dt="Espresso Sync Connection",
						dn=self.connection.name,
						args=json.dumps(args),
					)
				finally:
					del frappe.local.request

			return call

		return {
			"render_sample": lambda: esc.render_sample(
				json.dumps({"out": "{get_value:User:name:name=Administrator}"}), json.dumps({})
			),
			"sync_action": lambda: esc.sync_action(doc_arg),
			"process_sync_connection_form_action": lambda: sync_machine.process_sync_connection_form_action(
				doc_arg
			),
			"get_sample_data": doc_method("get_sample_data", shot_name=self.shot_name),
			"get_reference_docs": doc_method("get_reference_docs", doctype="ToDo"),
			"test_import": doc_method(
				"test_import", shot_name=self.shot_name, sample_object=json.dumps({"title": "x"})
			),
		}

	def test_every_whitelisted_endpoint_is_covered(self):
		import inspect

		whitelisted = {
			name
			for module in (esc, sync_machine)
			for name, fn in inspect.getmembers(module, inspect.isfunction)
			if fn in frappe.whitelisted
		} | {name for name, fn in vars(esc.EspressoSyncConnection).items() if fn in frappe.whitelisted}
		self.assertEqual(whitelisted, set(self.endpoints()))

	def test_website_user_is_refused(self):
		self.assert_refused(WEBSITE_USER)

	def test_desk_user_is_refused_even_with_share(self):
		self.assert_refused(DESK_USER)

		# nor can the share be used to change where the credentials are sent
		doc = frappe.get_doc("Espresso Sync Connection", self.connection.name).as_dict()
		doc["api_domain"] = "attacker.example.invalid"
		frappe.set_user(DESK_USER)
		self.assertTrue(frappe.has_permission("Espresso Sync Connection", "write", self.connection.name))
		with self.assertRaises(frappe.PermissionError):
			frappe.client.save(doc)
		frappe.set_user("Administrator")
		self.assertEqual(
			frappe.db.get_value("Espresso Sync Connection", self.connection.name, "api_domain"),
			"api.example.invalid",
		)

		frappe.set_user(MANAGER_USER)
		frappe.client.save(doc)
		self.assertEqual(
			frappe.db.get_value("Espresso Sync Connection", self.connection.name, "api_domain"),
			"attacker.example.invalid",
		)

	def assert_refused(self, user):
		with patch.object(
			requests.Session, "request", return_value=fake_response([{"title": "x"}])
		) as request:
			for name, call in self.endpoints().items():
				frappe.set_user(user)
				with self.subTest(endpoint=name, user=user), self.assertRaises(frappe.PermissionError):
					call()
				frappe.set_user("Administrator")
		request.assert_not_called()

	def test_system_manager_is_allowed(self):
		frappe.set_user(MANAGER_USER)
		with (
			patch.object(requests.Session, "request", return_value=fake_response([{"title": "x"}])),
			patch.object(esc.EspressoSyncConnection, "process_import_object", return_value={"ok": 1}),
		):
			for name, call in self.endpoints().items():
				with self.subTest(endpoint=name):
					call()  # must not raise

		frappe.set_user(MANAGER_USER)
		self.assertEqual(
			esc.render_sample(
				json.dumps({"out": "{get_value:User:name:name=Administrator}"}), json.dumps({})
			),
			{"out": "Administrator"},
		)

	def test_requests_use_a_timeout(self):
		connection = esc.get_connection(self.connection.name)
		shot = connection.shots[0]
		with patch.object(
			requests.Session, "request", return_value=fake_response([{"title": "x"}])
		) as request:
			connection.pull_import_data(shot)
			shot.override_import_request = 1
			shot.import_request_type = "POST"
			connection.pull_import_data(shot, payload="{}")
		self.assertEqual(request.call_count, 2)
		for call in request.call_args_list:
			self.assertEqual(call.kwargs.get("timeout"), REQUEST_TIMEOUT)

	def test_error_response_does_not_show_the_credentials(self):
		connection = esc.get_connection(self.connection.name)
		encoded = connection.get_request_headers()["Authorization"].split()[1]
		frappe.local.message_log = []
		with (
			patch.object(requests.Session, "request", return_value=fake_response({"echo": encoded}, 401)),
			self.assertRaises(frappe.ValidationError),
		):
			# a sample for the form: the error is shown, not logged
			connection.pull_import_data(connection.shots[0], single_pull=True)
		shown = json.dumps(frappe.local.message_log)
		self.assertIn("Invalid Server Response for https://api.example.invalid", shown)
		self.assertNotIn(encoded, shown)
		self.assertNotIn("hunter2-secret-value", shown)

	def test_failed_pull_log_does_not_log_the_credentials(self):
		connection = esc.get_connection(self.connection.name)
		encoded = connection.get_request_headers()["Authorization"].split()[1]
		connection.pull.sync_doctype = "ToDo"
		# a link that does not exist fails insert() before the Pull Log validates
		connection.pull.sync_doc = "does-not-exist"
		connection.pull.request = {"payload": None, "headers": connection.get_request_headers()}
		connection.pull.response = json.dumps({"echo": encoded})
		connection.pull.save()

		error = frappe.get_all(
			"Error Log",
			filters={"method": "Error saving pull log"},
			fields=["error"],
			order_by="creation desc",
			limit=1,
		)[0].error
		self.assertIn(connection.name, error)
		self.assertNotIn(encoded, error)
		self.assertNotIn("hunter2-secret-value", error)

	def test_rate_limited_session_defaults_the_timeout(self):
		session = RateLimitedSession(60)
		with patch.object(requests.Session, "request", return_value=fake_response({})) as request:
			session.request("GET", "https://api.example.invalid/x")
			session.request("POST", "https://api.example.invalid/x", timeout=5)
		self.assertEqual(request.call_args_list[0].kwargs["timeout"], REQUEST_TIMEOUT)
		self.assertEqual(request.call_args_list[1].kwargs["timeout"], 5)

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


class TestRetry(IntegrationTestCase):
	"""429 Too Many Requests: waited for and retried, a bounded number of times."""

	URL = f"{API}/limited"

	def send(self, *statuses_and_headers):
		session = RateLimitedSession()
		with (
			responses.RequestsMock(assert_all_requests_are_fired=False) as rsps,
			patch.object(requests_machine.time, "sleep") as sleep,
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
		self.assertEqual(waits[1], requests_machine.DEFAULT_BACKOFF * 2)

	def test_retries_are_bounded(self):
		response, calls, waits = self.send((429, {"Retry-After": "1"}))
		self.assertEqual(response.status_code, 429)
		self.assertEqual(calls, 1 + requests_machine.MAX_RETRIES)
		self.assertEqual(len(waits), requests_machine.MAX_RETRIES)

	def test_a_long_retry_after_is_not_waited_for(self):
		response, calls, waits = self.send((429, {"Retry-After": "3600"}), (200, {}))
		self.assertEqual((response.status_code, calls, waits), (429, 1, []))

	def test_a_sync_request_is_retried(self):
		connection = make_connection("ES Retry Test", do_import=1, id_field_map="id")
		with (
			responses.RequestsMock() as rsps,
			patch.object(requests_machine.time, "sleep"),
		):
			rsps.add(responses.GET, f"{API}/todos", status=429, headers={"Retry-After": "1"})
			rsps.add(responses.GET, f"{API}/todos", json=[{"id": "r1", "title": "es retried"}])
			connection.sync()
		self.assertTrue(frappe.db.exists("ToDo", {"description": "es retried"}))


class SyncTestCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		esc.ensure_sync_fields("ToDo")


class TestImport(SyncTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		# commits (custom fields, external IDs) outlive a test: each has its own Connection
		self.connection = make_connection(
			f"ES {self._testMethodName}",
			do_import=1,
			id_field_map="id",
			object_map_import=json.dumps({"description": "title", "status": "done ? 'Closed' : 'Open'"}),
		)
		self.shot = self.connection.shots[0]

	def run_import(self, *bodies, status=200):
		connection = esc.get_connection(self.connection.name)
		with responses.RequestsMock() as rsps:
			for body in bodies:
				rsps.add(responses.GET, f"{API}/todos", json=body, status=status)
			connection.sync()
		return connection

	def todo(self, external_id):
		names = frappe.get_all(
			"Espresso Sync ID",
			filters={
				"sync_connection": self.connection.name,
				"external_id": external_id,
				"parenttype": "ToDo",
			},
			pluck="parent",
		)
		self.assertEqual(len(names), 1, names)
		return frappe.get_doc("ToDo", names[0])

	def test_create_then_update(self):
		self.run_import(
			[{"id": "t1", "title": "es import one", "done": False}, {"id": "t2", "title": "es two"}]
		)
		first = self.todo("t1")
		self.assertEqual((first.description, first.status), ("es import one", "Open"))

		self.run_import([{"id": "t1", "title": "es import one, renamed", "done": True}])
		# the same document, saved
		updated = self.todo("t1")
		self.assertEqual(updated.name, first.name)
		self.assertEqual(
			frappe.db.get_value("ToDo", first.name, ["description", "status"]),
			("es import one, renamed", "Closed"),
		)
		self.assertEqual(frappe.db.count("ToDo", {"description": ("like", "es import one%")}), 1)

	def test_the_response_is_logged_once_per_request(self):
		self.run_import([{"id": "l1", "title": "es log one"}, {"id": "l2", "title": "es log two"}])
		logs = pull_logs(self.connection.name)
		self.assertEqual([log.sync_status for log in logs], ["Success"] * 3)
		self.assertIn("es log two", logs[0].response)
		self.assertEqual([bool(log.response) for log in logs], [True, False, False])
		self.assertEqual([json.loads(log.object).get("id") for log in logs], [None, "l1", "l2"])
		self.assertIsNotNone(frappe.db.get_value(esc.SHOT_DOCTYPE, self.shot.name, "last_import"))

	def test_a_failed_object_is_logged_and_the_run_goes_on(self):
		self.run_import([{"title": "es no id"}, {"id": "f2", "title": "es after the failure"}])
		self.assertEqual(self.todo("f2").description, "es after the failure")
		logs = pull_logs(self.connection.name)
		self.assertEqual([log.sync_status for log in logs], ["Success", "Failure", "Success"])
		self.assertEqual(json.loads(logs[1].diagnostics)[0]["severity"], "error")
		# a run with a failure does not move the watermark
		self.assertIsNone(frappe.db.get_value(esc.SHOT_DOCTYPE, self.shot.name, "last_import"))

	def test_the_status_is_checked_before_the_body(self):
		connection = esc.get_connection(self.connection.name)
		with responses.RequestsMock() as rsps:
			rsps.add(responses.GET, f"{API}/todos", body="<html>Bad Gateway</html>", status=502)
			connection.sync()  # must not raise
		[log] = pull_logs(self.connection.name)
		self.assertEqual(log.sync_status, "Failure")
		self.assertEqual(log.response, "<html>Bad Gateway</html>")
		self.assertEqual(json.loads(log.diagnostics)[0]["code"], "http-status")
		self.assertIsNone(frappe.db.get_value(esc.SHOT_DOCTYPE, self.shot.name, "last_import"))
		self.assertIsNotNone(
			frappe.db.get_value("Espresso Sync Connection", self.connection.name, "last_pull")
		)

	def test_a_body_that_is_not_json_is_a_failure(self):
		connection = esc.get_connection(self.connection.name)
		with responses.RequestsMock() as rsps:
			rsps.add(responses.GET, f"{API}/todos", body="not json", status=200)
			connection.sync()
		[log] = pull_logs(self.connection.name)
		self.assertEqual(json.loads(log.diagnostics)[0]["code"], "invalid-json")

	def test_sync_ids_are_matched_within_the_doctype(self):
		esc.ensure_sync_fields("Note")
		name = "es-same-name"
		frappe.get_doc({"doctype": "ToDo", "name": name, "description": "es unrelated"}).insert(set_name=name)
		note = frappe.get_doc({"doctype": "Note", "title": name, "content": "x"}).insert(set_name=name)
		note.append("espresso_sync_ids", {"sync_connection": self.connection.name, "external_id": "same"})
		note.save()

		self.run_import([{"id": "same", "title": "es imported"}])
		# the Note's sync ID is not this ToDo's: a new ToDo, and the unrelated one is untouched
		self.assertEqual(frappe.db.get_value("ToDo", name, "description"), "es unrelated")
		self.assertNotEqual(self.todo("same").name, name)

	def test_test_import_writes_nothing(self):
		self.connection.shots[0].object_map_import = json.dumps(
			{
				"{doctype}": "'Event'",
				"subject": "title",
				"event_type": "'Private'",
				"starts_on": "'2026-01-15'",
			}
		)
		self.connection.save()
		connection = esc.get_connection(self.connection.name)
		logs = frappe.db.count("Espresso Sync Pull Log")
		with patch.object(frappe.db, "commit", side_effect=AssertionError("committed")):
			doc = connection.test_import(self.shot.name, json.dumps({"id": "e1", "title": "es event"}))
		self.assertEqual((doc.doctype, doc.subject, doc.is_new()), ("Event", "es event", True))
		self.assertFalse(frappe.db.exists("Custom Field", {"dt": "Event", "fieldname": "exclude_from_sync"}))
		self.assertEqual(frappe.db.count("Espresso Sync Pull Log"), logs)


class TestExport(SyncTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		# a POST commits the external ID it gets: each test has its own Connection and documents
		self.prefix = f"es-{self._testMethodName}"
		self.connection = make_connection(
			f"ES {self._testMethodName}",
			do_export=1,
			object_map_export=json.dumps({"title": "description"}),
			filters=json.dumps([["ToDo", "description", "like", f"{self.prefix}-%"]]),
		)
		self.shot = self.connection.shots[0]
		base = datetime.datetime(2026, 1, 15, 9, 0)
		self.todos = []
		for i, name in enumerate(f"{self.prefix}-{suffix}" for suffix in "abc"):
			todo = frappe.get_doc({"doctype": "ToDo", "description": name}).insert()
			# a known order of `modified`, the order exports are sent in
			modified = base + datetime.timedelta(minutes=i)
			frappe.db.set_value("ToDo", todo.name, "modified", modified, update_modified=False)
			self.todos.append(frappe._dict(name=todo.name, modified=modified))

	def export(self, *replies):
		connection = esc.get_connection(self.connection.name)
		with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
			for method, url, status, body in replies:
				rsps.add(method, url, json=body, status=status)
			connection.process_export(connection.shots[0])
			return [(call.request.method, call.request.url) for call in rsps.calls]

	def external_id(self, todo):
		return frappe.db.get_value(
			"Espresso Sync ID",
			{"sync_connection": self.connection.name, "parenttype": "ToDo", "parent": todo.name},
			"external_id",
		)

	def test_post_then_put(self):
		calls = self.export(
			(responses.POST, f"{API}/todos", 201, {"id": "x1"}),
			(responses.POST, f"{API}/todos", 201, {"id": "x2"}),
			(responses.POST, f"{API}/todos", 201, {"id": "x3"}),
		)
		self.assertEqual(calls, [("POST", f"{API}/todos")] * 3)
		self.assertEqual([self.external_id(t) for t in self.todos], ["x1", "x2", "x3"])

		# a document with an external ID is updated in place
		calls = self.export(
			(responses.PUT, f"{API}/todos/x1", 200, {}),
			(responses.PUT, f"{API}/todos/x2", 200, {}),
			(responses.PUT, f"{API}/todos/x3", 200, {}),
		)
		self.assertEqual(
			calls, [("PUT", f"{API}/todos/x1"), ("PUT", f"{API}/todos/x2"), ("PUT", f"{API}/todos/x3")]
		)
		self.assertEqual(
			[(log.request_type, log.sync_status) for log in pull_logs(self.connection.name)][-3:],
			[("PUT", "Success")] * 3,
		)

	def test_the_watermark_stops_below_the_first_failure(self):
		self.export(
			(responses.POST, f"{API}/todos", 201, {"id": "w1"}),
			(responses.POST, f"{API}/todos", 500, {"error": "boom"}),
			(responses.POST, f"{API}/todos", 201, {"id": "w3"}),
		)
		# the failure did not stop the run, and the IDs already created are kept
		self.assertEqual([self.external_id(t) for t in self.todos], ["w1", None, "w3"])
		self.assertEqual(
			[(log.sync_doc, log.sync_status) for log in pull_logs(self.connection.name)],
			[
				(self.todos[0].name, "Success"),
				(self.todos[1].name, "Failure"),
				(self.todos[2].name, "Success"),
			],
		)
		self.assertEqual(
			frappe.db.get_value(esc.SHOT_DOCTYPE, self.shot.name, "last_export"), self.todos[0].modified
		)

	def test_a_failed_request_fails_that_document_only(self):
		connection = esc.get_connection(self.connection.name)
		with patch.object(
			connection.session.session,
			"request",
			side_effect=[
				fake_response({"id": "t1"}, 201),
				requests.Timeout("read timed out"),
				fake_response({}, 201),
			],
		) as request:
			connection.process_export(connection.shots[0])
		self.assertEqual(request.call_count, 3)
		for call in request.call_args_list:
			self.assertEqual(call.kwargs["timeout"], REQUEST_TIMEOUT)
		statuses = [log.sync_status for log in pull_logs(self.connection.name)]
		self.assertEqual(statuses, ["Success", "Failure", "Success"])

	def test_each_document_gets_its_own_url(self):
		self.connection.shots[0].uri = "todos/{id:description}"
		self.connection.save()
		with patch(
			"espresso_sync.map_machine.extract_dynamic_tag",
			side_effect=lambda tag, object, sync_connection, doc: (
				None if doc["name"] == self.todos[1].name else f"x-{doc['description']}"
			),
		):
			calls = self.export(
				(responses.POST, f"{API}/todos/x-{self.prefix}-a", 201, {}),
				(responses.POST, f"{API}/todos/x-{self.prefix}-c", 201, {}),
			)

		# the second has no value for its tag: it is not sent, and the third keeps its own URL
		self.assertEqual(
			calls, [("POST", f"{API}/todos/x-{self.prefix}-a"), ("POST", f"{API}/todos/x-{self.prefix}-c")]
		)
		self.assertEqual(
			[log.sync_status for log in pull_logs(self.connection.name)], ["Success", "Failure", "Success"]
		)


class TestExportWatermark(IntegrationTestCase):
	def test_export_watermark(self):
		t = [datetime.datetime(2026, 1, 15, 9, minute) for minute in range(4)]
		self.assertEqual(esc.export_watermark([], None), None)
		self.assertEqual(esc.export_watermark([(t[1], True), (t[2], True)], t[0]), t[2])
		self.assertEqual(esc.export_watermark([(t[1], True), (t[2], False), (t[3], True)], t[0]), t[1])
		# a failure at the same `modified` as a success holds the watermark below both
		self.assertEqual(esc.export_watermark([(t[1], True), (t[1], False)], t[0]), t[0])
		# never back
		self.assertEqual(esc.export_watermark([(t[1], True)], t[3]), t[3])
