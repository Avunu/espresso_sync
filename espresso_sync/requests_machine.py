import time
import requests

class RateLimitedSession:
    def __init__(self, max_requests_per_minute):
        self.session = requests.Session()
        self.max_requests_per_minute = max_requests_per_minute
        self.requests_made = 0
        self.time_first_request_was_made = None

    def request(self, *args, **kwargs):
        if self.requests_made >= self.max_requests_per_minute:
            elapsed_time = time.time() - self.time_first_request_was_made
            if elapsed_time < 60:
                time_to_sleep = 60 - elapsed_time
                time.sleep(time_to_sleep)

        if self.requests_made == 0 or time.time() - self.time_first_request_was_made >= 60:
            self.time_first_request_was_made = time.time()
            self.requests_made = 0

        response = self.session.request(*args, **kwargs)
        self.requests_made += 1
        return response
