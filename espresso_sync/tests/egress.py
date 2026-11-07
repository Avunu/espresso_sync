# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""Test helpers for requests sent through safe_fetch."""

import json
from unittest.mock import patch

import requests

from espresso_sync.utils import safe_fetch

# a public address the test API hosts (*.example.invalid) "resolve" to
PUBLIC_ADDRESS = "93.184.215.14"


def public_dns(address: str = PUBLIC_ADDRESS):
	"""Resolve every host to `address` (a public one by default): the test hosts do not
	resolve, and safe_fetch refuses a host it cannot resolve."""
	return patch.object(safe_fetch, "resolve", return_value=[address])


def make_response(payload=None, status_code=200, headers=None, body: bytes | None = None, url=""):
	"""A requests.Response with its body read, as Session.request returns it."""
	response = requests.Response()
	response.status_code = status_code
	response.headers.update(headers or {})
	response._content = body if body is not None else json.dumps(payload).encode()
	response._content_consumed = True
	response.url = url
	response.encoding = "utf-8"
	return response
