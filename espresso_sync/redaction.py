# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""Mask credentials before they are stored in an Espresso Sync Pull Log.

A single entry point, ``redact_pull_log_values``, is used both when a new
Pull Log row is written and by the patch that scrubs existing rows, so the two
can never disagree about what counts as a secret.

Rules:

- request headers: ``Authorization``, ``Proxy-Authorization``, the header name
  the Connection uses for header-based auth (its API Key field), and any
  header whose name contains auth, key, token, secret, passw, credential,
  signature, session or cookie have their value replaced;
- URLs: the user-info part (``https://user:pass@host``) is replaced, and so is
  the value of every query parameter whose name matches the same pattern;
- response, traceback and the imported object are read as JSON when they
  parse and get the same key-based masking as the request; otherwise, like
  any other free text, the value after one of those names
  (``Authorization: Basic ...``, ``'X-Api-Key': '...'``,
  ``"access_token": "..."``, ``client_secret=...``) and URL user-info are
  masked;
- every literal occurrence of the Connection's API secret (and, for Basic
  auth, the ``key:secret`` pair and its base64 form), also JSON-escaped,
  repr-escaped and URL-encoded, is replaced in every field, including the
  local document and the map.
"""

import base64
import copy
import json
import re
from functools import lru_cache
from urllib.parse import quote, quote_plus, urlsplit, urlunsplit

import frappe

REDACTED = "[redacted]"

SENSITIVE_HEADERS = frozenset({"authorization", "proxy-authorization"})
_SENSITIVE_WORD = (
	r"auth(?!or)|api[-_]?key|access[-_]?key|private[-_]?key|secret|token|passw|credential"
	r"|signature|session|cookie"
)
SENSITIVE_NAME = re.compile(rf"{_SENSITIVE_WORD}|^key$", re.IGNORECASE)
# the same names inside free text: the whole word around the match, or `key`
# (bounded, so a long token-like word cannot make the search quadratic)
_SENSITIVE_NAME_IN_TEXT = rf"[\w-]{{0,40}}(?:{_SENSITIVE_WORD})[\w-]{{0,40}}|key(?![\w-])"
URL_USERINFO = re.compile(r"(\b[a-zA-Z][a-zA-Z0-9+.-]*://)[^/?#@\s\"']+@")
URL_ONLY = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://\S*$")

# A literal secret shorter than this is not searched for in free text: masking
# every occurrence of a two-character string would destroy the log.
MIN_SECRET_LENGTH = 6

# fields holding data sent to or received from the API
PULL_LOG_TEXT_FIELDS = ("url", "request", "response", "traceback", "object")
# local data (the document written, the map used): only literal secrets are
# replaced, so a field that merely looks like a credential stays readable
PULL_LOG_LOCAL_FIELDS = ("document", "map")
PULL_LOG_FIELDS = PULL_LOG_TEXT_FIELDS + PULL_LOG_LOCAL_FIELDS


def _encoded_forms(value):
	"""`value` as it appears inside JSON text, a Python repr or a URL."""
	return {
		value,
		json.dumps(value)[1:-1],
		json.dumps(value, ensure_ascii=False)[1:-1],
		repr(value)[1:-1],
		quote(value, safe=""),
		quote_plus(value),
	}


def connection_secrets(connection_name):
	"""Return (header names, literal secret values) for an Espresso Sync Connection."""
	header_names, secrets = set(), set()
	if not connection_name or not frappe.db.exists("Espresso Sync Connection", connection_name):
		return header_names, secrets

	connection = frappe.get_doc("Espresso Sync Connection", connection_name)
	secret = connection.get_password("api_secret", raise_exception=False)
	if connection.auth_type == "Header-based" and connection.api_key:
		header_names.add(connection.api_key.strip().lower())
	if secret:
		secrets.update(_encoded_forms(secret))
		if connection.auth_type == "Basic":
			pair = f"{connection.api_key}:{secret}"
			secrets.update(_encoded_forms(pair))
			secrets.update(_encoded_forms(base64.b64encode(pair.encode()).decode()))
	return header_names, {s for s in secrets if len(s) >= MIN_SECRET_LENGTH}


def is_sensitive_name(name, header_names=()):
	name = str(name).strip().lower()
	return name in SENSITIVE_HEADERS or name in header_names or bool(SENSITIVE_NAME.search(name))


@lru_cache(maxsize=64)
def _header_value_pattern(header_names):
	"""Match `<sensitive name>: value`, `'<name>': 'value'` or `name=value` in unstructured text."""
	names = sorted(SENSITIVE_HEADERS | set(header_names), key=len, reverse=True)
	names = "|".join([*(re.escape(name) for name in names), _SENSITIVE_NAME_IN_TEXT])
	scheme = r"(?:Basic|Bearer|Token|Digest)\s+"
	return re.compile(
		rf"((?<![\w-])(?:{names})[\"']?\s*[:=]\s*)"
		# a quoted value up to its closing quote, or a bare value up to a separator;
		# a nested object or list is left to the names inside it
		rf"(?:(?P<quote>[\"'])(?P<qscheme>{scheme})?(?P<quoted>(?:\\.|(?!(?P=quote)).)*)(?P=quote)"
		rf"|(?P<scheme>{scheme})?(?![{{\[])(?P<bare>[^\"'\s,;&}}]+))",
		re.IGNORECASE,
	)


def _mask_value(match):
	quote_char = match.group("quote")
	if quote_char:
		value, scheme = match.group("quoted"), match.group("qscheme") or ""
	else:
		value, scheme = match.group("bare"), match.group("scheme") or ""
	if value == REDACTED:
		return match.group(0)
	masked = f"{scheme}{REDACTED}"
	return f"{match.group(1)}{quote_char}{masked}{quote_char}" if quote_char else f"{match.group(1)}{masked}"


def redact_literals(text, secrets=()):
	if not isinstance(text, str) or not text:
		return text
	# longest first so the base64 form of key:secret is replaced as a whole
	for secret in sorted(secrets, key=len, reverse=True):
		text = text.replace(secret, REDACTED)
	return text


def redact_text(text, secrets=(), header_names=()):
	if not isinstance(text, str) or not text:
		return text
	text = redact_literals(text, secrets)
	text = URL_USERINFO.sub(rf"\g<1>{REDACTED}@", text)
	return _header_value_pattern(frozenset(header_names)).sub(_mask_value, text)


def redact_url(url, secrets=()):
	if not isinstance(url, str) or not url:
		return url
	try:
		parts = urlsplit(url)
	except ValueError:
		return redact_text(url, secrets)

	netloc = parts.netloc
	if "@" in netloc:
		netloc = f"{REDACTED}@{netloc.rsplit('@', 1)[1]}"

	query = parts.query
	if query:
		pairs = []
		for pair in query.split("&"):
			name, sep, value = pair.partition("=")
			if sep and value and is_sensitive_name(name):
				value = REDACTED
			pairs.append(f"{name}{sep}{value}")
		query = "&".join(pairs)

	if (netloc, query) != (parts.netloc, parts.query):
		url = urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))
	return redact_text(url, secrets)


def _is_scalar(value):
	return isinstance(value, (str, int, float)) and not isinstance(value, bool)


def _redact_structure(value, header_names, secrets):
	if isinstance(value, dict):
		return {
			key: (
				REDACTED
				if is_sensitive_name(key, header_names) and _is_scalar(item)
				else _redact_structure(item, header_names, secrets)
			)
			for key, item in value.items()
		}
	if isinstance(value, list):
		return [_redact_structure(item, header_names, secrets) for item in value]
	if isinstance(value, str):
		if URL_ONLY.match(value):
			return redact_url(value, secrets)
		# a payload is usually JSON text itself
		return redact_request(value, header_names, secrets)
	return value


def redact_request(request, header_names=(), secrets=()):
	"""Redact a Pull Log request ({"payload": ..., "headers": {...}}), dict or JSON text.

	The value comes back in the type it was given; the input is never mutated,
	because the caller may still be using the same headers dict for requests.
	"""
	if isinstance(request, (dict, list)):
		return _redact_structure(copy.deepcopy(request), header_names, secrets)
	if not isinstance(request, str) or not request:
		return request
	try:
		parsed = json.loads(request)
	except ValueError:
		return redact_text(request, secrets, header_names)
	if not isinstance(parsed, (dict, list)):
		return redact_text(request, secrets, header_names)
	redacted = _redact_structure(parsed, header_names, secrets)
	if redacted == parsed:
		return request
	return json.dumps(redacted, indent=4, default=str)


def _as_text(value):
	if value is None or isinstance(value, str):
		return value
	if isinstance(value, (dict, list)):
		return json.dumps(value, indent=4, default=str)
	# e.g. an exception assigned to the traceback
	return frappe.utils.cstr(value)


def redact_pull_log_values(values, connection_name=None, secrets_cache=None):
	"""Return a copy of the Pull Log fields in ``values`` with secrets masked.

	``values`` is a mapping holding any of PULL_LOG_FIELDS; only the keys it
	contains are returned. ``secrets_cache`` (a dict) avoids decrypting the
	same Connection secret once per row.
	"""
	if secrets_cache is not None and connection_name in secrets_cache:
		header_names, secrets = secrets_cache[connection_name]
	else:
		header_names, secrets = connection_secrets(connection_name)
		if secrets_cache is not None:
			secrets_cache[connection_name] = (header_names, secrets)

	redacted = {}
	for field in PULL_LOG_FIELDS:
		if field not in values:
			continue
		value = values[field]
		if field == "request":
			# a dict is kept as a dict: the caller may serialise it differently
			redacted[field] = redact_request(value, header_names, secrets)
			continue
		value = _as_text(value)
		if field == "url":
			redacted[field] = redact_url(value, secrets)
		elif field in PULL_LOG_LOCAL_FIELDS:
			redacted[field] = redact_literals(value, secrets)
		else:
			# JSON when it parses, free text otherwise
			redacted[field] = redact_request(value, header_names, secrets)
	return redacted
