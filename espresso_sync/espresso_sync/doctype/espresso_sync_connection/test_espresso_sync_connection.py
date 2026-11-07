# Copyright (c) 2023, Avunu LLC and Contributors
# See license.txt

import ast
import json
from unittest.mock import MagicMock, patch

import frappe
import frappe.client
import frappe.handler
import requests
from frappe.share import add as share_doc
from frappe.tests import IntegrationTestCase

from espresso_sync import sync_machine
from espresso_sync.espresso_sync.doctype.espresso_sync_connection import espresso_sync_connection as esc
from espresso_sync.requests_machine import REQUEST_TIMEOUT, RateLimitedSession

WEBSITE_USER = "es-website-user@example.com"
DESK_USER = "es-desk-user@example.com"
MANAGER_USER = "es-manager@example.com"
DESK_ROLE = "Espresso Sync Test Desk Role"


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
	name="ES Permission Test", auth_type="Basic", api_key="sync-user", secret="hunter2-secret-value"
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


def inspect_source():
	import inspect

	return inspect.getsource(esc)


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
			"get_doctype_fields": lambda: esc.get_doctype_fields("ToDo"),
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
		self.assertIn("status", [f["fieldname"] for f in esc.get_doctype_fields("ToDo")])

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
			connection.pull_import_data(connection.shots[0])
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

	def test_export_requests_use_a_timeout(self):
		calls = [
			node
			for node in ast.walk(ast.parse(inspect_source()))
			if isinstance(node, ast.Call)
			and isinstance(node.func, ast.Attribute)
			and node.func.attr in ("get", "post", "put", "request")
			and ast.unparse(node.func.value) == "self.session"
		]
		self.assertGreaterEqual(len(calls), 4)
		for call in calls:
			with self.subTest(call=ast.unparse(call)):
				timeout = [k.value for k in call.keywords if k.arg == "timeout"]
				self.assertEqual([ast.unparse(v) for v in timeout], ["REQUEST_TIMEOUT"])

	def test_rate_limited_session_defaults_the_timeout(self):
		session = RateLimitedSession(60)
		with patch.object(requests.Session, "request", return_value=fake_response({})) as request:
			session.get("https://api.example.invalid/x")
			session.post("https://api.example.invalid/x", timeout=5)
		self.assertEqual(request.call_args_list[0].kwargs["timeout"], REQUEST_TIMEOUT)
		self.assertEqual(request.call_args_list[1].kwargs["timeout"], 5)
