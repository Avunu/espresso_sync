# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""The one way this app sends a request to an external API.

Every request goes through ``RateLimitedSession.request``, which adds the
timeout, keeps to the Connection's rate limit and, when the API answers
429 Too Many Requests, waits as its ``Retry-After`` says and tries again, a
bounded number of times.
"""

import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import requests

# (connect, read) seconds for every call to an external API
REQUEST_TIMEOUT = (10, 60)
# after a 429, how many more times a request is sent (so at most 1 + MAX_RETRIES requests)
MAX_RETRIES = 3
# a Retry-After longer than this (seconds) is not waited for: the 429 is returned
MAX_RETRY_AFTER = 60
# the wait before the first retry when the 429 has no usable Retry-After, doubled each time
DEFAULT_BACKOFF = 1.0


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
	"""A requests.Session that sends at most ``max_requests_per_minute`` requests a
	minute (no limit when it is empty or 0), and retries a 429."""

	def __init__(self, max_requests_per_minute: int | None = None):
		self.session = requests.Session()
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

	def request(self, method, url, **kwargs) -> requests.Response:
		kwargs.setdefault("timeout", REQUEST_TIMEOUT)
		attempt = 0
		while True:
			self._wait_for_rate_limit()
			response = self.session.request(method, url, **kwargs)
			self.requests_made += 1
			if response.status_code != 429 or attempt >= MAX_RETRIES:
				return response
			delay = retry_delay(response, attempt)
			if delay is None:
				return response
			response.close()
			time.sleep(delay)
			attempt += 1
