# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

import json
import re
import socket
import threading
import time
from typing import cast
from unittest.mock import patch

import frappe
import requests
import responses
from frappe.tests import IntegrationTestCase
from requests.adapters import HTTPAdapter

from espresso_sync.espresso_sync.doctype.espresso_sync_connection import espresso_sync_connection as esc
from espresso_sync.requests_machine import RateLimitedSession
from espresso_sync.tests.egress import PUBLIC_ADDRESS, public_dns
from espresso_sync.utils import safe_fetch
from espresso_sync.utils.safe_fetch import EgressError, safe_request

API = "https://api.example.invalid/v1"
OTHER = "https://other.example.invalid/v1"
SECRET = {"Authorization": "Basic c3luYzpodW50ZXIy"}


def loopback_server(test, head: bytes, trickle: bool = True, drip: bytes = b"x") -> int:
	"""The port of a server on the loopback address that answers with `head`, then (when
	`trickle`) `drip` every 0.2 seconds, holding the connection open."""
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
			while trickle and not stop.wait(0.2):
				try:
					connection.sendall(drip)
				except OSError:
					return

	thread = threading.Thread(target=serve, daemon=True)
	thread.start()

	def cleanup():
		stop.set()
		listener.close()
		thread.join(5)

	test.addCleanup(cleanup)
	return listener.getsockname()[1]


class TestAddresses(IntegrationTestCase):
	def test_only_http_and_https(self):
		for url in (
			"file:///etc/passwd",
			"ftp://api.example.invalid/x",
			"gopher://api.example.invalid/",
			"//api.example.invalid/x",
			"https:///x",
			"https://api.example.invalid:99999/x",
		):
			with self.subTest(url=url), self.assertRaises(requests.RequestException):
				safe_request("GET", url)

	def test_private_and_metadata_addresses_are_refused_before_sending(self):
		for address in (
			"169.254.169.254",
			"169.254.170.2",
			"127.0.0.1",
			"10.1.2.3",
			"172.16.0.1",
			"192.168.1.1",
			"100.64.0.1",
			"0.0.0.0",
			"::1",
			"fe80::1",
			"fd00:ec2::254",
			"::ffff:127.0.0.1",
		):
			with (
				self.subTest(address=address),
				public_dns(address),
				responses.RequestsMock(assert_all_requests_are_fired=False) as rsps,
			):
				rsps.add(responses.GET, f"{API}/x", body="secret")
				with self.assertRaises(EgressError):
					safe_request("GET", f"{API}/x")
				self.assertEqual(len(rsps.calls), 0)
		with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
			rsps.add(responses.GET, "http://169.254.169.254/latest/meta-data/", body="secret")
			with self.assertRaises(EgressError):
				safe_request("GET", "http://169.254.169.254/latest/meta-data/")
			self.assertEqual(len(rsps.calls), 0)

	def test_one_private_address_among_public_ones_is_enough(self):
		with public_dns(PUBLIC_ADDRESS, "127.0.0.1"), self.assertRaises(EgressError):
			safe_request("GET", f"{API}/x")

	def test_a_host_that_does_not_resolve_is_refused(self):
		with (
			patch.object(socket, "getaddrinfo", side_effect=socket.gaierror("no such host")),
			self.assertRaises(EgressError),
		):
			safe_request("GET", f"{API}/x")

	def test_a_dns_answer_that_changes_cannot_reach_a_private_address(self):
		# the host is public when checked, and loopback when connected to
		port = loopback_server(self, b"HTTP/1.1 200 OK\r\nContent-Length: 6\r\n\r\nsecret", trickle=False)
		real_getaddrinfo = socket.getaddrinfo
		answers = iter([PUBLIC_ADDRESS])

		def rebinding(host, port, *args, **kwargs):
			if host != "api.example.invalid":
				return real_getaddrinfo(host, port, *args, **kwargs)
			address = next(answers, "127.0.0.1")
			return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

		with patch.object(socket, "getaddrinfo", rebinding), self.assertRaises(EgressError):
			safe_request("GET", f"http://api.example.invalid:{port}/x")

	def test_the_session_takes_no_proxy_from_the_environment_and_does_not_retry(self):
		session = safe_fetch.make_session()
		self.assertFalse(session.trust_env)
		self.assertEqual(cast(HTTPAdapter, session.get_adapter(API)).max_retries.total, 0)


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
		self.assertFalse(safe_fetch.credentials_apply("ftp://api.example.invalid/x", allowed))
		# the host urllib3 connects to, not the one urlsplit reads after a backslash
		self.assertFalse(
			safe_fetch.credentials_apply("https://other.example.invalid\\@api.example.invalid/x", allowed)
		)
		self.assertFalse(
			safe_fetch.credentials_apply(
				"http://other.example.invalid:8080\\@api.example.invalid:8080/x", f"{allowed}:8080"
			)
		)
		self.assertTrue(safe_fetch.credentials_apply("https://API.example.invalid./x", allowed))
		self.assertTrue(safe_fetch.credentials_apply("https://[::1]:8443/x", "[::1]:8443"))

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

	def test_a_backslash_before_the_allowed_host_does_not_take_the_credentials_elsewhere(self):
		# urlsplit reads the host as api.example.invalid, urllib3 connects to other.example.invalid
		tricky = "https://other.example.invalid\\@api.example.invalid"
		elsewhere = re.compile(r"https://other\.example\.invalid/.*")
		with responses.RequestsMock() as rsps:
			rsps.add(responses.GET, elsewhere, json={})
			safe_request("GET", f"{tricky}/x", credentials=SECRET, allowed_host="api.example.invalid")
			self.assertNotIn("Authorization", rsps.calls[0].request.headers)
		with responses.RequestsMock() as rsps:
			rsps.add(responses.GET, f"{API}/x", status=302, headers={"Location": f"{tricky}/stolen"})
			rsps.add(responses.GET, elsewhere, json={})
			safe_request("GET", f"{API}/x", credentials=SECRET, allowed_host="api.example.invalid")
			self.assertEqual(rsps.calls[0].request.headers.get("Authorization"), SECRET["Authorization"])
			self.assertTrue(rsps.calls[1].request.url.startswith("https://other.example.invalid/"))
			self.assertNotIn("Authorization", rsps.calls[1].request.headers)

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
			with self.assertRaises(EgressError):
				safe_request("GET", f"{API}/x")
			self.assertEqual(len(rsps.calls), 1)

	def test_redirects_are_capped(self):
		with responses.RequestsMock() as rsps:
			for hop in range(safe_fetch.MAX_REDIRECTS + 1):
				rsps.add(responses.GET, f"{API}/{hop}", status=307, headers={"Location": f"{API}/{hop + 1}"})
			with self.assertRaises(EgressError):
				safe_request("GET", f"{API}/0")

	def test_a_redirected_post(self):
		with responses.RequestsMock() as rsps:
			rsps.add(responses.POST, f"{API}/x", status=303, headers={"Location": "/v1/y"})
			rsps.add(responses.GET, f"{API}/y", json={})
			rsps.add(responses.POST, f"{API}/a", status=307, headers={"Location": "/v1/b"})
			rsps.add(responses.POST, f"{API}/b", json={})
			safe_request("POST", f"{API}/x", json={"a": 1})
			safe_request("POST", f"{API}/a", json={"a": 1})
			# 303 asks for a GET without the body, 307 for the same request again
			self.assertEqual(rsps.calls[1].request.method, "GET")
			self.assertIsNone(rsps.calls[1].request.body)
			self.assertEqual(rsps.calls[3].request.method, "POST")
			self.assertEqual(json.loads(rsps.calls[3].request.body), {"a": 1})

	def test_the_size_cap(self):
		with responses.RequestsMock() as rsps:
			rsps.add(responses.GET, f"{API}/big", body=b"x" * 2048)
			rsps.add(responses.GET, f"{API}/declared", body=b"x", headers={"Content-Length": "999999"})
			with self.assertRaises(EgressError):
				safe_request("GET", f"{API}/big", max_bytes=1024)
			with self.assertRaises(EgressError):
				safe_request("GET", f"{API}/declared", max_bytes=1024)

	def test_the_deadline(self):
		with (
			responses.RequestsMock() as rsps,
			patch.object(safe_fetch, "DEADLINE", -1),
			self.assertRaises(EgressError),
		):
			rsps.add(responses.GET, f"{API}/slow", body=b"x" * 10)
			safe_request("GET", f"{API}/slow")

	def test_the_deadline_holds_for_a_body_that_trickles_in(self):
		# each byte comes well within the read timeout; the whole never arrives in time. A
		# plain session: Frappe's guard would refuse the loopback server
		for name, head in (
			("a body with a length", b"HTTP/1.1 200 OK\r\nContent-Length: 100000\r\n\r\n"),
			("a chunked body", b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n1000\r\n"),
			("a body read to the end", b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n"),
		):
			url = f"http://127.0.0.1:{loopback_server(self, head)}/spec.json"
			with (
				self.subTest(name),
				patch.object(safe_fetch, "DEADLINE", 1),
				self.assertRaises(EgressError),
			):
				started = time.monotonic()
				try:
					safe_request("GET", url, session=requests.Session(), timeout=(2, 3))
				finally:
					self.assertLess(time.monotonic() - started, 4)

	def test_the_headers_are_bounded_by_the_read_timeout_not_the_deadline(self):
		# the deadline's timer starts once the headers are in: until then, each read waits at
		# most the read timeout, and the worker's or job's timeout bounds the whole
		port = loopback_server(self, b"HTTP/1.1 200 OK\r\n", drip=b"")
		url = f"http://127.0.0.1:{port}/x"
		with patch.object(safe_fetch, "DEADLINE", 30), self.assertRaises(requests.Timeout):
			started = time.monotonic()
			try:
				safe_request("GET", url, session=requests.Session(), timeout=(2, 1))
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
			"other.example.invalid\\",
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
		self.assertIn("EgressError", log.traceback)

	def test_requests_still_time_out(self):
		with (
			patch.object(requests.Session, "request", side_effect=requests.Timeout("slow")),
			self.assertRaises(requests.Timeout),
		):
			safe_request("GET", f"{API}/x")
