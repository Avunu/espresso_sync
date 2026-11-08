# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""Every request this app sends to another host goes through here.

``safe_request`` sends one request and refuses it unless:

- the URL is http or https, with a host and no ``user:password@``;
- every address the host resolves to is a public one: loopback, private, link-local
  (169.254.169.254, the cloud metadata address, among them), shared, reserved and
  multicast ranges are refused, unless the site config lists the range in
  ``espresso_sync_private_networks`` (the metadata addresses never);
- it is redirected at most ``max_redirects`` times, each hop checked again;
- the response is no larger than ``max_bytes`` and arrives within ``deadline`` seconds.

Credentials are passed apart from the other headers, and are added only when the host
the request goes to (each hop of a redirect included) is the ``allowed_host`` given, on
its port (the scheme's default port when the allowed host names none), and never to an
http hop of a request that began on https.

The deadline holds for the whole exchange: a watchdog shuts the connection when it
passes, however slowly the headers or the body trickle in.

The connection itself is made to the address that was checked (``make_session``'s
adapter re-resolves and re-checks when it connects), so a DNS answer that changes
between the check and the connection cannot reach a private address.
"""

import contextlib
import contextvars
import ipaddress
import socket
import threading
import time
from collections.abc import Mapping
from typing import Any, cast
from urllib.parse import urljoin, urlsplit

import frappe
import requests
from frappe import _
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import ConnectTimeoutError, NameResolutionError, NewConnectionError
from urllib3.util import connection as urllib3_connection

# (connect, read) seconds
REQUEST_TIMEOUT = (10, 60)
# seconds for a whole exchange, redirects and body included, however slowly it trickles in
DEFAULT_DEADLINE = 120
MAX_REDIRECTS = 5
# the largest response body read (after decompression)
DEFAULT_MAX_BYTES = 20 * 1024 * 1024
DEFAULT_PORTS = {"http": 80, "https": 443}
# never reachable, whatever the site config allows: the cloud metadata services
METADATA_NETWORKS = (
	ipaddress.ip_network("169.254.169.254/32"),
	ipaddress.ip_network("169.254.170.2/32"),
	ipaddress.ip_network("fd00:ec2::254/128"),
)
NAT64_NETWORK = ipaddress.ip_network("64:ff9b::/96")
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

type IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class EgressError(requests.RequestException):
	"""A request this app refuses to send, or a response it refuses to read."""


class EgressRefused(EgressError):
	"""The URL, its host or one of the host's addresses is not allowed."""


class ResponseTooLarge(EgressError):
	"""The response body is larger than the cap."""


class EgressTimeout(EgressError, requests.Timeout):
	"""The response did not arrive whole within the deadline."""


def private_networks_allowed() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
	"""The ranges the site config (``espresso_sync_private_networks``) opens, e.g. an
	on-premises API at 10.1.2.3: ["10.1.2.0/24"]."""
	configured = frappe.conf.get("espresso_sync_private_networks") or []
	if isinstance(configured, str):
		configured = [configured]
	networks = []
	for value in configured:
		try:
			networks.append(ipaddress.ip_network(str(value).strip(), strict=False))
		except ValueError:
			continue
	return networks


def unwrap(address: IPAddress) -> IPAddress:
	"""The IPv4 address an IPv6 one carries (IPv4-mapped, NAT64), else the address."""
	if isinstance(address, ipaddress.IPv6Address):
		if address.ipv4_mapped:
			return address.ipv4_mapped
		if address in NAT64_NETWORK:
			return ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
	return address


def address_allowed(address: IPAddress) -> bool:
	address = unwrap(address)
	if any(address in network for network in METADATA_NETWORKS):
		return False
	if address.is_global and not address.is_multicast:
		return True
	return any(address in network for network in private_networks_allowed())


def resolve(host: str, port: int) -> list[str]:
	"""The addresses `host` resolves to (a literal address resolves to itself)."""
	infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
	return list(dict.fromkeys(str(info[4][0]) for info in infos))


def checked_address(host: str, port: int) -> str:
	"""Resolve `host` and return the address to connect to; refuse the host when any
	address it resolves to is not allowed."""
	try:
		addresses = [str(ipaddress.ip_address(host))]
	except ValueError:
		addresses = None
	try:
		addresses = addresses or resolve(host, port)
	except (OSError, UnicodeError) as e:
		raise EgressRefused(_("{0} could not be resolved: {1}").format(host, str(e))) from e
	if not addresses:
		raise EgressRefused(_("{0} could not be resolved").format(host))
	for value in addresses:
		# a scoped IPv6 address ("fe80::1%eth0") is link-local: never allowed
		try:
			address = ipaddress.ip_address(value)
		except ValueError:
			raise EgressRefused(_("{0} resolves to {1}, which is not allowed").format(host, value)) from None
		if not address_allowed(address):
			raise EgressRefused(_("{0} resolves to {1}, which is not allowed").format(host, value))
	return addresses[0]


def split_host(value: str) -> tuple[str, int | None]:
	"""("api.example.com", 8443) from "api.example.com:8443"; the host lower-cased, without
	a trailing dot or IPv6 brackets."""
	parts = urlsplit(f"//{value.strip()}")
	host = (parts.hostname or "").rstrip(".")
	return host, parts.port


def normalize_allowed_host(value: str | None) -> str:
	"""The canonical form of an allowed host ("host" or "host:port"), or "" when `value`
	is empty. Raises ValueError for anything else: a scheme, a path, credentials."""
	value = (value or "").strip()
	if not value:
		return ""
	if "/" in value or "@" in value or "?" in value or "#" in value or " " in value:
		raise ValueError(value)
	host, port = split_host(value)
	if not host:
		raise ValueError(value)
	if ":" in host:
		host = f"[{host}]"
	return f"{host}:{port}" if port else host


def host_of(url_or_domain: str | None) -> str:
	"""The allowed-host form of a URL's or a domain's host ("" when there is none)."""
	value = (url_or_domain or "").strip()
	if not value:
		return ""
	if "://" not in value:
		value = f"https://{value}"
	parts = urlsplit(value)
	try:
		return normalize_allowed_host(parts.netloc.rsplit("@", 1)[-1])
	except ValueError:
		return ""


def check_url(url: str) -> tuple[str, str, int]:
	"""(scheme, host, port) of a URL that may be requested; EgressRefused otherwise."""
	try:
		parts = urlsplit(url)
		port = parts.port
	except ValueError as e:
		raise EgressRefused(_("{0} is not a valid URL").format(url)) from e
	scheme = parts.scheme.lower()
	if scheme not in DEFAULT_PORTS:
		raise EgressRefused(_("Only http and https URLs are allowed, not {0}").format(url))
	if parts.username is not None or parts.password is not None:
		raise EgressRefused(_("A URL must not carry credentials"))
	host = (parts.hostname or "").rstrip(".")
	if not host:
		raise EgressRefused(_("{0} has no host").format(url))
	return scheme, host, port or DEFAULT_PORTS[scheme]


def credentials_apply(url: str, allowed_host: str | None) -> bool:
	"""Whether a request to `url` may carry the credentials of a Connection whose allowed
	host is `allowed_host`: the host is the same, and so is the port, which is the URL
	scheme's default (443, or 80 for http) when the allowed host names none."""
	if not allowed_host:
		return False
	try:
		allowed, allowed_port = split_host(allowed_host)
		scheme, host, port = check_url(url)
	except EgressRefused, ValueError:
		return False
	if not allowed or host.lower() != allowed.lower():
		return False
	return port == (allowed_port or DEFAULT_PORTS[scheme])


def _connect(conn: HTTPConnection):
	"""urllib3's HTTPConnection._new_conn, connecting to the checked address of the host
	(the TLS server name stays the host)."""
	try:
		address = checked_address(conn.host, conn.port or 0)
	except EgressRefused as e:
		raise NewConnectionError(conn, str(e)) from e
	try:
		return urllib3_connection.create_connection(
			(address, conn.port),
			conn.timeout,
			source_address=conn.source_address,
			socket_options=conn.socket_options,
		)
	except socket.gaierror as e:
		raise NameResolutionError(conn.host, conn, e) from e
	except TimeoutError as e:
		raise ConnectTimeoutError(conn, f"Connection to {conn.host} timed out") from e
	except OSError as e:
		raise NewConnectionError(conn, f"Failed to establish a new connection: {e}") from e


def shut(sock: socket.socket):
	"""End the socket's exchange: a read waiting on it returns at once, and finds the end."""
	with contextlib.suppress(OSError):
		sock.shutdown(socket.SHUT_RDWR)


class Watchdog:
	"""Shuts the sockets of one safe_request when its deadline passes, so that a response
	trickling in (a byte at a time, each within the read timeout) still ends."""

	def __init__(self, seconds: float):
		self.sockets: list[socket.socket] = []
		self.fired = False
		self.lock = threading.Lock()
		self.timer = threading.Timer(max(seconds, 0), self.fire)
		self.timer.daemon = True

	def watch(self, sock: socket.socket | None):
		if sock is None:
			return
		with self.lock:
			self.sockets.append(sock)
			fired = self.fired
		if fired:
			shut(sock)

	def fire(self):
		with self.lock:
			self.fired = True
			sockets = list(self.sockets)
		for sock in sockets:
			shut(sock)

	def __enter__(self):
		self.token = WATCHDOG.set(self)
		self.timer.start()
		return self

	def __exit__(self, *_exc_info):
		self.timer.cancel()
		WATCHDOG.reset(self.token)


# the watchdog of the safe_request under way in this thread (or task)
WATCHDOG: contextvars.ContextVar[Watchdog | None] = contextvars.ContextVar(
	"espresso_sync_watchdog", default=None
)


def watched(conn: HTTPConnection):
	"""Put the connection's socket under the watchdog of the safe_request under way. The
	socket, not the connection: http.client lets go of the connection's socket when the
	response is to be read until the connection closes."""
	watchdog = WATCHDOG.get()
	if watchdog is not None:
		watchdog.watch(cast(Any, conn.sock))


class GuardedHTTPConnection(HTTPConnection):
	def _new_conn(self):
		return _connect(self)

	def request(self, *args, **kwargs):
		watched(self)
		return super().request(*args, **kwargs)

	def getresponse(self, *args, **kwargs):
		watched(self)
		return super().getresponse(*args, **kwargs)


class GuardedHTTPSConnection(HTTPSConnection):
	def _new_conn(self):
		return _connect(self)

	def request(self, *args, **kwargs):
		watched(self)
		return super().request(*args, **kwargs)

	def getresponse(self, *args, **kwargs):
		watched(self)
		return super().getresponse(*args, **kwargs)


class GuardedHTTPConnectionPool(HTTPConnectionPool):
	ConnectionCls = cast(Any, GuardedHTTPConnection)


class GuardedHTTPSConnectionPool(HTTPSConnectionPool):
	ConnectionCls = cast(Any, GuardedHTTPSConnection)


class GuardedAdapter(HTTPAdapter):
	"""An adapter whose connections go only to checked addresses."""

	def init_poolmanager(self, *args, **kwargs):
		super().init_poolmanager(*args, **kwargs)
		cast(Any, self.poolmanager).pool_classes_by_scheme = {
			"http": GuardedHTTPConnectionPool,
			"https": GuardedHTTPSConnectionPool,
		}

	def proxy_manager_for(self, proxy, **proxy_kwargs):
		# a proxy would be connected to instead of the checked address
		del proxy_kwargs
		raise EgressRefused(_("Requests through a proxy ({0}) are not allowed").format(proxy))


def make_session() -> requests.Session:
	"""A session for safe_request: no proxies or .netrc from the environment, and
	connections only to checked addresses."""
	session = requests.Session()
	session.trust_env = False
	adapter = GuardedAdapter()
	session.mount("http://", adapter)
	session.mount("https://", adapter)
	return session


def read_capped(response: requests.Response, max_bytes: int, deadline: float) -> None:
	"""Read the body into the response, refusing more than `max_bytes` or a body that has
	not arrived by `deadline` (a time.monotonic() value)."""
	declared = response.headers.get("Content-Length", "")
	if declared.isdigit() and int(declared) > max_bytes:
		response.close()
		raise ResponseTooLarge(_("The response is larger than {0} bytes").format(max_bytes))
	body = bytearray()
	try:
		for chunk in response.iter_content(64 * 1024):
			body += chunk
			if len(body) > max_bytes:
				raise ResponseTooLarge(_("The response is larger than {0} bytes").format(max_bytes))
			if time.monotonic() > deadline:
				raise EgressTimeout(_("The response did not arrive in time"))
	finally:
		response.close()
	response._content = bytes(body)


def redirected(status: int, method: str, kwargs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
	"""The method and arguments of the request a redirect asks for: 303 (and 301/302 of
	anything but GET or HEAD) becomes a GET without a body; 307/308 repeat the request."""
	if (status == 303 and method != "HEAD") or (status in (301, 302) and method not in ("GET", "HEAD")):
		return "GET", {key: value for key, value in kwargs.items() if key not in ("data", "json", "files")}
	return method, kwargs


def follow_redirects(
	session: requests.Session,
	method: str,
	url: str,
	*,
	headers: Mapping[str, str] | None,
	credentials: Mapping[str, str] | None,
	allowed_host: str | None,
	max_bytes: int,
	max_redirects: int,
	until: float,
	timeout: Any,
	**kwargs: Any,
) -> requests.Response:
	began_on_https = urlsplit(url).scheme.lower() == "https"
	for _hop in range(max_redirects + 1):
		if time.monotonic() > until:
			raise EgressTimeout(_("The response did not arrive in time"))
		scheme, host, port = check_url(url)
		checked_address(host, port)
		send_headers = dict(headers or {})
		if credentials and credentials_apply(url, allowed_host) and not (began_on_https and scheme == "http"):
			send_headers.update(credentials)
		response = session.request(
			method,
			url,
			headers=send_headers,
			timeout=timeout,
			allow_redirects=False,
			stream=True,
			**kwargs,
		)
		location = response.headers.get("Location")
		if response.status_code not in REDIRECT_STATUSES or not location:
			read_capped(response, max_bytes, until)
			return response
		response.close()
		url = urljoin(response.url or url, location)
		method, kwargs = redirected(response.status_code, method, kwargs)
	raise EgressRefused(_("More than {0} redirects").format(max_redirects))


def safe_request(
	method: str,
	url: str,
	*,
	session: requests.Session | None = None,
	headers: Mapping[str, str] | None = None,
	credentials: Mapping[str, str] | None = None,
	allowed_host: str | None = None,
	max_bytes: int = DEFAULT_MAX_BYTES,
	max_redirects: int = MAX_REDIRECTS,
	deadline: float = DEFAULT_DEADLINE,
	timeout: Any = REQUEST_TIMEOUT,
	**kwargs: Any,
) -> requests.Response:
	"""Send a request under the checks above and return its response, body read.

	`credentials` are headers (Authorization, an API key header) added only when the
	host of the request is `allowed_host` (see credentials_apply), and never to an http
	hop after an https one. Raises EgressError (a requests.RequestException) for a request
	refused or a response too large or too slow, and requests' own exceptions for the
	rest."""
	session = session or make_session()
	method = method.upper()
	until = time.monotonic() + deadline
	with Watchdog(deadline) as watchdog:
		try:
			response = follow_redirects(
				session,
				method,
				url,
				headers=headers,
				credentials=credentials,
				allowed_host=allowed_host,
				max_bytes=max_bytes,
				max_redirects=max_redirects,
				until=until,
				timeout=timeout,
				**kwargs,
			)
		except requests.RequestException as e:
			if watchdog.fired and not isinstance(e, EgressError):
				raise EgressTimeout(_("The response did not arrive in time")) from e
			raise
		if watchdog.fired:
			# the connection was shut: a body read to its end may have been cut short
			raise EgressTimeout(_("The response did not arrive in time"))
	return response
