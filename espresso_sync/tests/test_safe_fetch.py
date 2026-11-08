# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

import ipaddress
import json
import socket
import threading
import time
from typing import cast
from unittest.mock import patch

import frappe
import requests
import responses
from frappe.tests import IntegrationTestCase
from urllib3.exceptions import NewConnectionError

from espresso_sync.espresso_sync.doctype.espresso_sync_connection import espresso_sync_connection as esc
from espresso_sync.patches import set_connection_allowed_host
from espresso_sync.requests_machine import RateLimitedSession
from espresso_sync.tests.egress import PUBLIC_ADDRESS, public_dns
from espresso_sync.utils import safe_fetch
from espresso_sync.utils.safe_fetch import EgressRefused, EgressTimeout, ResponseTooLarge, safe_request

API = "https://api.example.invalid/v1"
OTHER = "https://other.example.invalid/v1"
SECRET = {"Authorization": "Basic c3luYzpodW50ZXIy"}


def trickling_server(test, head: bytes) -> str:
	"""The URL of a server on the loopback address that answers with `head`, then a byte
	every 0.2 seconds; the loopback range is opened for the test."""
	listener = socket.create_server(("127.0.0.1", 0))
	listener.settimeout(10)
	stop = threading.Event()

	def serve():
		try:
			connection, _address = listener.accept()
		except OSError:
			return
		with connection:
			connection.recv(65536)
			connection.sendall(head)
			while not stop.wait(0.2):
				try:
					connection.sendall(b"x")
				except OSError:
					return

	thread = threading.Thread(target=serve, daemon=True)
	thread.start()

	def cleanup():
		stop.set()
		listener.close()
		thread.join(5)

	test.addCleanup(cleanup)
	test.enterContext(
		patch.object(
			safe_fetch, "private_networks_allowed", return_value=[ipaddress.ip_network("127.0.0.0/8")]
		)
	)
	return f"http://127.0.0.1:{listener.getsockname()[1]}/spec.json"


class TestUrlChecks(IntegrationTestCase):
	def test_only_http_and_https(self):
		for url in (
			"file:///etc/passwd",
			"ftp://api.example.invalid/x",
			"gopher://api.example.invalid/",
			"//api.example.invalid/x",
			"https:///x",
			"https://user:pw@api.example.invalid/x",
			"https://api.example.invalid:99999/x",
		):
			with self.subTest(url=url), self.assertRaises(EgressRefused):
				safe_request("GET", url)

	def test_private_and_metadata_addresses_are_refused(self):
		for address in (
			"169.254.169.254",
			"127.0.0.1",
			"10.1.2.3",
			"172.16.0.1",
			"192.168.1.1",
			"100.64.0.1",
			"0.0.0.0",
			"224.0.0.1",
			"::1",
			"fe80::1",
			"fd00::1",
			"::ffff:127.0.0.1",
			"64:ff9b::a9fe:a9fe",
		):
			with self.subTest(address=address):
				self.assertFalse(safe_fetch.address_allowed(safe_fetch.ipaddress.ip_address(address)))
		self.assertTrue(safe_fetch.address_allowed(safe_fetch.ipaddress.ip_address(PUBLIC_ADDRESS)))

	def test_a_literal_metadata_address_is_refused_before_sending(self):
		with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
			rsps.add(responses.GET, "http://169.254.169.254/latest/meta-data/", body="secret")
			with self.assertRaises(EgressRefused):
				safe_request("GET", "http://169.254.169.254/latest/meta-data/")
			self.assertEqual(len(rsps.calls), 0)

	def test_a_host_resolving_to_a_private_address_is_refused(self):
		with public_dns("10.0.0.5"), self.assertRaises(EgressRefused):
			safe_request("GET", f"{API}/x")
		# one private address among public ones is enough
		with (
			patch.object(safe_fetch, "resolve", return_value=[PUBLIC_ADDRESS, "127.0.0.1"]),
			self.assertRaises(EgressRefused),
		):
			safe_request("GET", f"{API}/x")

	def test_a_host_that_does_not_resolve_is_refused(self):
		with (
			patch.object(safe_fetch.socket, "getaddrinfo", side_effect=OSError("no such host")),
			self.assertRaises(EgressRefused),
		):
			safe_request("GET", f"{API}/x")

	def test_the_site_config_can_open_a_private_network(self):
		with (
			public_dns("10.1.2.3"),
			patch.dict(
				frappe.local.conf, {"espresso_sync_private_networks": ["10.1.2.0/24", "not a network"]}
			),
			responses.RequestsMock() as rsps,
		):
			rsps.add(responses.GET, f"{API}/x", json={"ok": 1})
			self.assertEqual(safe_request("GET", f"{API}/x").json(), {"ok": 1})
		# never the metadata address
		with patch.dict(frappe.local.conf, {"espresso_sync_private_networks": "169.254.0.0/16"}):
			self.assertFalse(safe_fetch.address_allowed(safe_fetch.ipaddress.ip_address("169.254.169.254")))
			self.assertTrue(safe_fetch.address_allowed(safe_fetch.ipaddress.ip_address("169.254.1.1")))


class TestConnections(IntegrationTestCase):
	"""The connection is made to the address that was checked, whatever DNS says later."""

	def test_a_connection_to_a_private_address_is_refused(self):
		conn = safe_fetch.GuardedHTTPSConnection("api.example.invalid", 443)
		with public_dns("127.0.0.1"), self.assertRaises(NewConnectionError):
			conn._new_conn()

	def test_the_connection_goes_to_the_checked_address(self):
		conn = safe_fetch.GuardedHTTPConnection("api.example.invalid", 80)
		with (
			public_dns(),
			patch.object(
				safe_fetch.urllib3_connection, "create_connection", return_value="socket"
			) as connect,
		):
			self.assertEqual(conn._new_conn(), "socket")
		self.assertEqual(connect.call_args.args[0], (PUBLIC_ADDRESS, 80))
		# the TLS server name and the Host header stay the host
		self.assertEqual(conn.host, "api.example.invalid")

	def test_connection_errors_are_urllib3_errors(self):
		conn = safe_fetch.GuardedHTTPConnection("api.example.invalid", 80)
		for error, expected in (
			(safe_fetch.socket.gaierror("x"), safe_fetch.NameResolutionError),
			(TimeoutError("x"), safe_fetch.ConnectTimeoutError),
			(ConnectionRefusedError("x"), NewConnectionError),
		):
			with (
				self.subTest(error=error),
				public_dns(),
				patch.object(safe_fetch.urllib3_connection, "create_connection", side_effect=error),
				self.assertRaises(expected),
			):
				conn._new_conn()

	def test_the_session_uses_the_guarded_pools_and_no_proxy(self):
		session = safe_fetch.make_session()
		self.assertFalse(session.trust_env)
		adapter = cast(safe_fetch.GuardedAdapter, session.get_adapter("https://api.example.invalid/"))
		self.assertIsInstance(adapter, safe_fetch.GuardedAdapter)
		pool = adapter.poolmanager.connection_from_url("https://api.example.invalid/")
		self.assertIs(pool.ConnectionCls, safe_fetch.GuardedHTTPSConnection)
		with self.assertRaises(EgressRefused):
			adapter.proxy_manager_for("http://proxy.example.invalid:3128")


class TestRequests(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.enterContext(public_dns())

	def test_credentials_go_only_to_the_allowed_host(self):
		with responses.RequestsMock() as rsps:
			rsps.add(responses.GET, f"{API}/x", json={})
			rsps.add(responses.GET, f"{OTHER}/x", json={})
			rsps.add(responses.GET, "https://api.example.invalid:8443/x", json={})
			safe_request("GET", f"{API}/x", credentials=SECRET, allowed_host="api.example.invalid")
			safe_request("GET", f"{OTHER}/x", credentials=SECRET, allowed_host="api.example.invalid")
			safe_request(
				"GET",
				"https://api.example.invalid:8443/x",
				credentials=SECRET,
				allowed_host="api.example.invalid:443",
			)
			sent = [call.request.headers.get("Authorization") for call in rsps.calls]
		self.assertEqual(sent, [SECRET["Authorization"], None, None])

	def test_credentials_are_bound_to_the_port_and_scheme(self):
		allowed = "api.example.invalid"
		self.assertTrue(safe_fetch.credentials_apply("https://api.example.invalid/x", allowed))
		self.assertTrue(safe_fetch.credentials_apply("http://api.example.invalid/x", allowed))
		# no port named: the scheme's default port only
		self.assertFalse(safe_fetch.credentials_apply("https://api.example.invalid:8443/x", allowed))
		self.assertFalse(safe_fetch.credentials_apply("http://api.example.invalid:8080/x", allowed))
		self.assertTrue(safe_fetch.credentials_apply("http://api.example.invalid:8080/x", f"{allowed}:8080"))
		self.assertFalse(safe_fetch.credentials_apply("http://api.example.invalid/x", f"{allowed}:8080"))

	def test_a_redirect_to_http_or_another_port_drops_the_credentials(self):
		plain = "http://api.example.invalid/v1"
		for location in (
			f"{plain}/y",
			"http://api.example.invalid:8080/v1/y",
			f"{API.replace('/v1', ':8443/v1')}/y",
		):
			with self.subTest(location=location), responses.RequestsMock() as rsps:
				rsps.add(responses.GET, f"{API}/x", status=302, headers={"Location": location})
				rsps.add(responses.GET, location, json={})
				safe_request("GET", f"{API}/x", credentials=SECRET, allowed_host="api.example.invalid")
				self.assertEqual(rsps.calls[0].request.headers.get("Authorization"), SECRET["Authorization"])
				self.assertNotIn("Authorization", rsps.calls[1].request.headers)
		# an upgrade from http to https keeps them, as requests does
		with responses.RequestsMock() as rsps:
			rsps.add(responses.GET, f"{plain}/x", status=301, headers={"Location": f"{API}/x"})
			rsps.add(responses.GET, f"{API}/x", json={})
			safe_request("GET", f"{plain}/x", credentials=SECRET, allowed_host="api.example.invalid")
			sent = [call.request.headers.get("Authorization") for call in rsps.calls]
		self.assertEqual(sent, [SECRET["Authorization"], SECRET["Authorization"]])

	def test_no_allowed_host_no_credentials(self):
		with responses.RequestsMock() as rsps:
			rsps.add(responses.GET, f"{API}/x", json={})
			safe_request("GET", f"{API}/x", credentials=SECRET, allowed_host=None)
			self.assertNotIn("Authorization", rsps.calls[0].request.headers)

	def test_a_redirect_off_host_drops_the_credentials(self):
		with responses.RequestsMock() as rsps:
			rsps.add(responses.GET, f"{API}/x", status=302, headers={"Location": f"{OTHER}/y"})
			rsps.add(responses.GET, f"{OTHER}/y", json={"moved": 1})
			response = safe_request(
				"GET", f"{API}/x", credentials={"X-Api-Key": "k3y"}, allowed_host="api.example.invalid"
			)
			self.assertEqual(response.json(), {"moved": 1})
			self.assertEqual(rsps.calls[0].request.headers.get("X-Api-Key"), "k3y")
			self.assertNotIn("X-Api-Key", rsps.calls[1].request.headers)

	def test_a_redirect_to_a_private_address_is_refused(self):
		with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
			rsps.add(
				responses.GET,
				f"{API}/x",
				status=301,
				headers={"Location": "http://169.254.169.254/latest/meta-data/"},
			)
			rsps.add(responses.GET, "http://169.254.169.254/latest/meta-data/", body="secret")
			with self.assertRaises(EgressRefused):
				safe_request("GET", f"{API}/x")
			self.assertEqual(len(rsps.calls), 1)

	def test_redirects_are_capped(self):
		with responses.RequestsMock() as rsps:
			for hop in range(safe_fetch.MAX_REDIRECTS + 1):
				rsps.add(responses.GET, f"{API}/{hop}", status=307, headers={"Location": f"{API}/{hop + 1}"})
			with self.assertRaises(EgressRefused):
				safe_request("GET", f"{API}/0")

	def test_a_redirect_method(self):
		body = {"json": {"a": 1}, "params": {"q": 1}}
		self.assertEqual(safe_fetch.redirected(303, "POST", body), ("GET", {"params": {"q": 1}}))
		self.assertEqual(safe_fetch.redirected(302, "POST", body), ("GET", {"params": {"q": 1}}))
		self.assertEqual(safe_fetch.redirected(307, "POST", body), ("POST", body))
		self.assertEqual(safe_fetch.redirected(301, "GET", body), ("GET", body))
		self.assertEqual(safe_fetch.redirected(303, "HEAD", body), ("HEAD", body))
		with responses.RequestsMock() as rsps:
			rsps.add(responses.POST, f"{API}/x", status=303, headers={"Location": "/v1/y"})
			rsps.add(responses.GET, f"{API}/y", json={})
			safe_request("POST", f"{API}/x", json={"a": 1})
			self.assertEqual(rsps.calls[1].request.method, "GET")
			self.assertIsNone(rsps.calls[1].request.body)

	def test_the_size_cap(self):
		with responses.RequestsMock() as rsps:
			rsps.add(responses.GET, f"{API}/big", body=b"x" * 2048)
			rsps.add(responses.GET, f"{API}/declared", body=b"x", headers={"Content-Length": "999999"})
			with self.assertRaises(ResponseTooLarge):
				safe_request("GET", f"{API}/big", max_bytes=1024)
			with self.assertRaises(ResponseTooLarge):
				safe_request("GET", f"{API}/declared", max_bytes=1024)

	def test_the_deadline(self):
		with responses.RequestsMock() as rsps:
			rsps.add(responses.GET, f"{API}/slow", body=b"x" * 10)
			with self.assertRaises(EgressTimeout):
				safe_fetch.read_capped(requests.get(f"{API}/slow", stream=True), 1024, time.monotonic() - 1)
			with self.assertRaises(EgressTimeout):
				safe_request("GET", f"{API}/slow", deadline=-1)

	def test_the_deadline_holds_for_a_response_that_trickles_in(self):
		# each byte comes well within the read timeout; the whole never arrives in time
		for name, head in (
			("a body with a length", b"HTTP/1.1 200 OK\r\nContent-Length: 100000\r\n\r\n"),
			("a chunked body", b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n1000\r\n"),
			("a body read to the end", b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n"),
			("the headers", b"HTTP/1.1 200 OK\r\n"),
		):
			url = trickling_server(self, head)
			with self.subTest(name), self.assertRaises(EgressTimeout):
				started = time.monotonic()
				try:
					safe_request("GET", url, deadline=1, timeout=(2, 3))
				finally:
					self.assertLess(time.monotonic() - started, 4)

	def test_the_body_is_read(self):
		with responses.RequestsMock() as rsps:
			rsps.add(responses.GET, f"{API}/x", json={"a": [1, 2]})
			response = safe_request("GET", f"{API}/x")
		self.assertEqual(response.json(), {"a": [1, 2]})
		self.assertEqual(json.loads(response.text), {"a": [1, 2]})

	def test_the_rate_limited_session_passes_the_credentials_on(self):
		with responses.RequestsMock() as rsps:
			rsps.add(responses.GET, f"{API}/x", json={})
			rsps.add(responses.GET, f"{OTHER}/x", json={})
			session = RateLimitedSession()
			session.request("GET", f"{API}/x", credentials=SECRET, allowed_host="api.example.invalid")
			session.request("GET", f"{OTHER}/x", credentials=SECRET, allowed_host="api.example.invalid")
			self.assertEqual(rsps.calls[0].request.headers.get("Authorization"), SECRET["Authorization"])
			self.assertNotIn("Authorization", rsps.calls[1].request.headers)


class TestAllowedHost(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.enterContext(public_dns())
		frappe.set_user("Administrator")

	def make_connection(self, name, **values):
		name = f"ES Allowed Host {name}"
		if frappe.db.exists("Espresso Sync Connection", name):
			frappe.delete_doc("Espresso Sync Connection", name, force=True)
		return frappe.get_doc(
			{
				"doctype": "Espresso Sync Connection",
				"connection_name": name,
				"auth_type": "Header-based",
				"api_key": "X-Api-Key",
				"api_secret": "allowed-host-secret",
				"api_domain": "api.example.invalid",
				"api_base": "/v1",
				"sync_frequency": "Manual",
				**values,
			}
		).insert(ignore_permissions=True)

	def test_normalize_and_host_of(self):
		self.assertEqual(safe_fetch.normalize_allowed_host(" API.Example.invalid. "), "api.example.invalid")
		self.assertEqual(
			safe_fetch.normalize_allowed_host("api.example.invalid:8443"), "api.example.invalid:8443"
		)
		self.assertEqual(safe_fetch.normalize_allowed_host("[::1]:8443"), "[::1]:8443")
		self.assertEqual(safe_fetch.normalize_allowed_host(""), "")
		for bad in (
			"https://api.example.invalid",
			"api.example.invalid/v1",
			"user@api.example.invalid",
			":80",
		):
			with self.subTest(bad=bad), self.assertRaises(ValueError):
				safe_fetch.normalize_allowed_host(bad)
		self.assertEqual(
			safe_fetch.host_of("https://user@API.example.invalid:8443/v1"), "api.example.invalid:8443"
		)
		self.assertEqual(safe_fetch.host_of("api.example.invalid"), "api.example.invalid")
		self.assertEqual(safe_fetch.host_of(None), "")
		self.assertFalse(safe_fetch.credentials_apply("not a url", "api.example.invalid"))

	def test_it_is_filled_from_the_api_domain(self):
		connection = self.make_connection("filled")
		self.assertEqual(connection.allowed_host, "api.example.invalid")
		connection.allowed_host = "https://elsewhere.example.invalid/x"
		self.assertRaises(frappe.ValidationError, connection.save)

	def test_a_shot_on_another_host_gets_no_credentials(self):
		connection = self.make_connection(
			"override",
			shots=[
				{
					"dt": "ToDo",
					"uri": "todos",
					"do_import": 1,
					"id_field_map": "id",
					"override_api_domain": 1,
					"api_domain": "other.example.invalid",
					"object_map_import": json.dumps({"description": "title"}),
				}
			],
		)
		connection = esc.get_connection(str(connection.name))
		with responses.RequestsMock() as rsps:
			rsps.add(responses.GET, f"{OTHER}/todos", json=[])
			connection.pull_import_data(connection.shots[0])
			self.assertNotIn("X-Api-Key", rsps.calls[0].request.headers)
		diagnostics = json.loads(
			frappe.get_all(
				"Espresso Sync Pull Log",
				filters={"sync_connection": connection.name},
				pluck="diagnostics",
				order_by="creation desc",
				limit=1,
			)[0]
		)
		self.assertEqual(diagnostics[0]["code"], "credentials-withheld")

	def test_an_import_request_refused_is_logged(self):
		connection = self.make_connection(
			"refused",
			api_domain="169.254.169.254",
			shots=[{"dt": "ToDo", "uri": "todos", "do_import": 1, "object_map_import": "{}"}],
		)
		connection = esc.get_connection(str(connection.name))
		self.assertEqual(connection.pull_import_data(connection.shots[0]), [])
		log = frappe.get_all(
			"Espresso Sync Pull Log",
			filters={"sync_connection": connection.name},
			fields=["sync_status", "traceback"],
			order_by="creation desc",
			limit=1,
		)[0]
		self.assertEqual(log.sync_status, "Failure")
		self.assertIn("EgressRefused", log.traceback)

	def test_the_patch_derives_it_from_the_urls(self):
		plain = self.make_connection("patch plain")
		moved = self.make_connection(
			"patch moved",
			shots=[
				{
					"dt": "ToDo",
					"uri": "a",
					"override_api_domain": 1,
					"api_domain": "moved.example.invalid:8443",
				},
			],
		)
		split = self.make_connection(
			"patch split",
			shots=[
				{"dt": "ToDo", "uri": "a"},
				{"dt": "ToDo", "uri": "b", "override_api_domain": 1, "api_domain": "other.example.invalid"},
			],
		)
		empty = self.make_connection("patch empty", api_domain="")
		for doc in (plain, moved, split, empty):
			frappe.db.set_value("Espresso Sync Connection", doc.name, "allowed_host", None)
		set_connection_allowed_host.execute()
		values = {
			doc.name: frappe.db.get_value("Espresso Sync Connection", doc.name, "allowed_host")
			for doc in (plain, moved, split, empty)
		}
		self.assertEqual(
			values,
			{
				plain.name: "api.example.invalid",
				moved.name: "moved.example.invalid:8443",
				split.name: "api.example.invalid",
				empty.name: None,
			},
		)

	def test_requests_still_time_out(self):
		with (
			patch.object(requests.Session, "request", side_effect=requests.Timeout("slow")),
			self.assertRaises(requests.Timeout),
		):
			safe_request("GET", f"{API}/x")
