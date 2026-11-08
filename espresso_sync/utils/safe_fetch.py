# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""Every request this app sends to another host goes through ``safe_request``.

The request goes through Frappe's guarded session (``get_safe_request_session``), which
refuses anything but http and https, a proxy, and any address that is not globally
routable (loopback, private, link-local such as the cloud metadata address
169.254.169.254, shared and reserved ranges): on every hop, and again on the connected
socket, so a DNS answer that changes in between cannot reach a private address.

On top of it, ``safe_request`` follows redirects itself, at most MAX_REDIRECTS of them,
because only then can it decide for each hop whether the credentials go along: only to
the ``allowed_host``, on its port (the scheme's default when it names none), read from
the URL as urllib3 reads it to connect, and never to an http hop of a request that
began on https. It reads at most ``max_bytes`` of the body, and gives up on a body
still arriving DEADLINE seconds after the request began. The deadline does not cover
the status line and headers: those are bounded by the read timeout of each read, and in
the end by the web worker's or the background job's own timeout.

A sync sends its requests through ``RateLimitedSession``, which keeps to the Connection's
rate limit and, when the API answers 429 Too Many Requests, waits as its ``Retry-After``
says and tries again, a bounded number of times.
"""

import contextlib
import threading
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin, urlsplit

import requests
from frappe import _
from frappe.utils.safe_exec import BlockedRequest, get_safe_request_session
from urllib3.util import Retry, Url, parse_url

# (connect, read) seconds
REQUEST_TIMEOUT = (10, 60)
# seconds for a whole exchange, redirects and body included
DEADLINE = 120
MAX_REDIRECTS = 5
# the largest response body read (after decompression)
DEFAULT_MAX_BYTES = 20 * 1024 * 1024
DEFAULT_PORTS = {"http": 80, "https": 443}
# after a 429, how many more times a request is sent (so at most 1 + MAX_RETRIES requests)
MAX_RETRIES = 3
# a Retry-After longer than this (seconds) is not waited for: the 429 is returned
MAX_RETRY_AFTER = 60
# the wait before the first retry when the 429 has no usable Retry-After, doubled each time
DEFAULT_BACKOFF = 1.0


class EgressError(requests.RequestException):
	"""A request refused, or a response too large or too slow."""


def split_host(value: str) -> tuple[str, int | None]:
	"""("api.example.com", 8443) from "api.example.com:8443"; the host lower-cased, without
	a trailing dot or IPv6 brackets."""
	parts = urlsplit(f"//{value.strip()}")
	return (parts.hostname or "").rstrip("."), parts.port


def normalize_allowed_host(value: str | None) -> str:
	"""The canonical form of an allowed host ("host" or "host:port"), or "" when `value`
	is empty. Raises ValueError for anything else: a scheme, a path, credentials."""
	value = (value or "").strip()
	if not value:
		return ""
	if any(char in value for char in "/\\@?# "):
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
	try:
		return normalize_allowed_host(urlsplit(value).netloc.rsplit("@", 1)[-1])
	except ValueError:
		return ""


def connect_target(url: str) -> Url:
	"""The scheme, host and port of `url` as requests and urllib3 read it, the ones they
	connect to: urlsplit can read the same URL otherwise ("http://a\\@b/" is host b to it,
	host a to urllib3). Raises ValueError for a URL requests refuses."""
	try:
		return parse_url(requests.Request("GET", url).prepare().url or "")
	except requests.RequestException as e:
		raise ValueError(url) from e


def credentials_apply(url: str, allowed_host: str | None) -> bool:
	"""Whether a request to `url` may carry the credentials of a Connection whose allowed
	host is `allowed_host`: the host requests connects to is the same, and so is the
	port, which is the URL scheme's default (443, or 80 for http) when the allowed host
	names none."""
	if not allowed_host:
		return False
	try:
		target = connect_target(url)
		allowed = connect_target(f"{target.scheme}://{allowed_host}/")
	except ValueError:
		return False
	default_port = DEFAULT_PORTS.get(target.scheme or "")
	host = (target.host or "").rstrip(".")
	return bool(default_port and allowed.host and host == allowed.host.rstrip(".")) and (
		target.port or default_port
	) == (allowed.port or default_port)


def make_session() -> requests.Session:
	"""Frappe's guarded session, without its retries: urllib3 would wait out any
	Retry-After a 429 sends, however long, and RateLimitedSession retries a 429 itself."""
	session = get_safe_request_session()
	for adapter in session.adapters.values():
		adapter.max_retries = Retry(0, read=False)
	return session


def shut(response: requests.Response):
	"""Shut the response's socket, so that a read blocked on it returns at once."""
	with contextlib.suppress(AttributeError, ValueError, RuntimeError, OSError):
		response.raw.shutdown()


def read_body(response: requests.Response, max_bytes: int, until: float) -> None:
	"""Read the body into the response: at most `max_bytes`, and only what has arrived by
	`until` (a time.monotonic() value)."""
	too_large = _("The response is larger than {0} bytes").format(max_bytes)
	declared = response.headers.get("Content-Length", "")
	if declared.isdigit() and int(declared) > max_bytes:
		response.close()
		raise EgressError(too_large)
	# a timer, as the read timeout holds for each read only: a body trickling in a byte at a
	# time would never end
	timer = threading.Timer(max(until - time.monotonic(), 0), shut, [response])
	timer.daemon = True
	timer.start()
	body = bytearray()
	try:
		for chunk in response.iter_content(64 * 1024):
			body += chunk
			if len(body) > max_bytes:
				raise EgressError(too_large)
	except requests.RequestException:
		# a read the timer cut short is the deadline's error
		if time.monotonic() < until:
			raise
	finally:
		timer.cancel()
		response.close()
	if time.monotonic() >= until:
		raise EgressError(_("The response did not arrive in time"))
	response._content = bytes(body)


def safe_request(
	method: str,
	url: str,
	*,
	session: requests.Session | None = None,
	headers: Mapping[str, str] | None = None,
	credentials: Mapping[str, str] | None = None,
	allowed_host: str | None = None,
	max_bytes: int = DEFAULT_MAX_BYTES,
	timeout: Any = REQUEST_TIMEOUT,
	**kwargs: Any,
) -> requests.Response:
	"""Send a request under the checks above and return its response, body read.

	`credentials` are headers (Authorization, an API key header) added only when the host
	of the request is `allowed_host` (see credentials_apply), and never to an http hop
	after an https one. Raises EgressError (a requests.RequestException) for a request
	refused or a response too large or too slow, and requests' own exceptions for the
	rest."""
	session = session or make_session()
	method = method.upper()
	until = time.monotonic() + DEADLINE
	began_on_https = urlsplit(url).scheme.lower() == "https"
	for _hop in range(MAX_REDIRECTS + 1):
		send_headers = dict(headers or {})
		downgraded = began_on_https and urlsplit(url).scheme.lower() != "https"
		if credentials and credentials_apply(url, allowed_host) and not downgraded:
			send_headers.update(credentials)
		try:
			response = session.request(
				method,
				url,
				headers=send_headers,
				timeout=timeout,
				allow_redirects=False,
				stream=True,
				**kwargs,
			)
		except BlockedRequest as e:
			raise EgressError(str(e)) from e
		if not response.is_redirect:
			read_body(response, max_bytes, until)
			return response
		response.close()
		url = urljoin(response.url or url, response.headers["Location"])
		if response.status_code in (301, 302, 303) and method != "HEAD":
			# as browsers treat them: the redirected request is a GET, without the body
			method = "GET"
			kwargs = {key: value for key, value in kwargs.items() if key not in ("data", "json", "files")}
	raise EgressError(_("More than {0} redirects").format(MAX_REDIRECTS))


def retry_delay(response: requests.Response, attempt: int) -> float | None:
	"""Seconds to wait before retrying a 429 response, or None to give up.

	``Retry-After`` is read as delay-seconds or as an HTTP date. Without it, the
	wait is DEFAULT_BACKOFF doubled for each earlier attempt.
	"""
	backoff = DEFAULT_BACKOFF * 2**attempt
	value = (response.headers.get("Retry-After") or "").strip()
	if not value:
		return backoff
	if value.isdigit():
		delay = float(value)
	else:
		try:
			when = parsedate_to_datetime(value)
		except TypeError, ValueError:
			return backoff
		if when.tzinfo is None:
			when = when.replace(tzinfo=UTC)
		delay = max((when - datetime.now(UTC)).total_seconds(), 0.0)
	return delay if delay <= MAX_RETRY_AFTER else None


class RateLimitedSession:
	"""A session that sends at most ``max_requests_per_minute`` requests a minute (no
	limit when it is empty or 0), and retries a 429."""

	def __init__(self, max_requests_per_minute: int | None = None):
		self.session = make_session()
		self.max_requests_per_minute = max_requests_per_minute or 0
		self.requests_made = 0
		self.time_first_request_was_made = 0.0

	def _wait_for_rate_limit(self):
		if not self.max_requests_per_minute:
			return
		if self.requests_made >= self.max_requests_per_minute:
			elapsed_time = time.time() - self.time_first_request_was_made
			if elapsed_time < 60:
				time.sleep(60 - elapsed_time)

		if self.requests_made == 0 or time.time() - self.time_first_request_was_made >= 60:
			self.time_first_request_was_made = time.time()
			self.requests_made = 0

	def request(self, method, url, *, credentials=None, allowed_host=None, **kwargs) -> requests.Response:
		"""safe_request through this session: `credentials` (headers) go only to
		`allowed_host`."""
		attempt = 0
		while True:
			self._wait_for_rate_limit()
			response = safe_request(
				method,
				url,
				session=self.session,
				credentials=credentials,
				allowed_host=allowed_host,
				**kwargs,
			)
			self.requests_made += 1
			if response.status_code != 429 or attempt >= MAX_RETRIES:
				return response
			delay = retry_delay(response, attempt)
			if delay is None:
				return response
			response.close()
			time.sleep(delay)
			attempt += 1
