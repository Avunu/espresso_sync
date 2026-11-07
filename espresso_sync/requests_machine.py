# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

import time

import requests

# (connect, read) seconds for every call to an external API
REQUEST_TIMEOUT = (10, 60)


class RateLimitedSession:
	def __init__(self, max_requests_per_minute):
		self.session = requests.Session()
		self.max_requests_per_minute = max_requests_per_minute
		self.requests_made = 0
		self.time_first_request_was_made = 0.0

	def request(self, *args, **kwargs):
		if self.requests_made >= self.max_requests_per_minute:
			elapsed_time = time.time() - self.time_first_request_was_made
			if elapsed_time < 60:
				time_to_sleep = 60 - elapsed_time
				time.sleep(time_to_sleep)

		if self.requests_made == 0 or time.time() - self.time_first_request_was_made >= 60:
			self.time_first_request_was_made = time.time()
			self.requests_made = 0

		kwargs.setdefault("timeout", REQUEST_TIMEOUT)
		response = self.session.request(*args, **kwargs)
		self.requests_made += 1
		return response

	def get(self, *args, **kwargs):
		return self.request("GET", *args, **kwargs)

	def patch(self, *args, **kwargs):
		return self.request("PATCH", *args, **kwargs)

	def post(self, *args, **kwargs):
		return self.request("POST", *args, **kwargs)

	def put(self, *args, **kwargs):
		return self.request("PUT", *args, **kwargs)

	def delete(self, *args, **kwargs):
		return self.request("DELETE", *args, **kwargs)
