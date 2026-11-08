# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""Test helpers for requests sent through safe_fetch."""

import json
import socket
from unittest.mock import patch

import requests

# a public address the test API hosts (*.example.invalid) "resolve" to
PUBLIC_ADDRESS = "93.184.215.14"
TEST_DOMAIN = ".example.invalid"


def public_dns(*addresses: str):
	"""Resolve the test hosts (*.example.invalid) to `addresses`, a public one by default:
	they do not resolve, and Frappe's guard refuses a host it cannot resolve. Every other
	host resolves as usual."""
	real_getaddrinfo = socket.getaddrinfo

	def getaddrinfo(host, port, *args, **kwargs):
		if not str(host).endswith(TEST_DOMAIN):
			return real_getaddrinfo(host, port, *args, **kwargs)
		return [
			(
				socket.AF_INET6 if ":" in address else socket.AF_INET,
				socket.SOCK_STREAM,
				6,
				"",
				(address, port),
			)
			for address in addresses or (PUBLIC_ADDRESS,)
		]

	return patch.object(socket, "getaddrinfo", getaddrinfo)


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
