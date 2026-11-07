# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""Scheduled syncs.

Each scheduler event (hooks.scheduler_events) calls process_sync_connections
with its frequency, which enqueues one background job per enabled Connection
whose Sync Frequency matches. A Connection never has two syncs at once: its
job has a fixed job_id and is enqueued with deduplicate=True, so a second one
is not queued while the first is queued or running, and the job itself takes a
cache lock before it syncs.
"""

from contextlib import suppress
from datetime import datetime
from typing import cast

import frappe
from croniter import croniter
from frappe.utils import get_datetime, now_datetime
from frappe.utils.redis_wrapper import RedisWrapper
from redis.exceptions import LockError
from redis.lock import Lock

CONNECTION = "Espresso Sync Connection"
# the scheduler event -> the Connection's Sync Frequency it runs
FREQUENCIES = {
	"all": "Every Minute",
	"hourly": "Hourly",
	"daily": "Daily",
	"weekly": "Weekly",
	"monthly": "Monthly",
	"cron": "Cron",
}
JOB_QUEUE = "long"
JOB_TIMEOUT = 60 * 60
# held for at most as long as the job may run, so a killed job cannot keep it
LOCK_TIMEOUT = JOB_TIMEOUT


def cron_is_due(cron_rule: str | None, since, now: datetime) -> bool:
	"""Whether `cron_rule` fires after `since` and by `now` (as frappe's own cron jobs are read)."""
	if not cron_rule or not croniter.is_valid(cron_rule):
		return False
	return croniter(cron_rule, get_datetime(since)).get_next(datetime) <= now


def connections_due(frequency: str, now: datetime | None = None) -> list[str]:
	sync_frequency = FREQUENCIES[frequency]
	if sync_frequency != "Cron":
		return frappe.get_all(
			CONNECTION,
			filters={"pull_shot": 1, "sync_frequency": sync_frequency},
			pluck="name",
			order_by="name asc",
		)
	now = now or now_datetime()
	rows = frappe.get_all(
		CONNECTION,
		filters={"pull_shot": 1, "sync_frequency": "Cron"},
		fields=["name", "cron_rule", "last_pull", "creation"],
		order_by="name asc",
	)
	return [row.name for row in rows if cron_is_due(row.cron_rule, row.last_pull or row.creation, now)]


def sync_job_id(connection: str) -> str:
	return f"espresso_sync:sync:{connection}"


def enqueue_connection_sync(connection: str):
	frappe.enqueue(
		"espresso_sync.scheduler.run_connection_sync",
		queue=JOB_QUEUE,
		timeout=JOB_TIMEOUT,
		job_id=sync_job_id(connection),
		deduplicate=True,
		connection=connection,
	)


def process_sync_connections(frequency: str) -> list[str]:
	"""Enqueue a sync of every enabled Connection due at this scheduler event; return their names."""
	names = connections_due(frequency)
	for name in names:
		enqueue_connection_sync(name)
	return names


def sync_all():
	process_sync_connections("all")


def sync_hourly():
	process_sync_connections("hourly")


def sync_daily():
	process_sync_connections("daily")


def sync_weekly():
	process_sync_connections("weekly")


def sync_monthly():
	process_sync_connections("monthly")


def sync_cron():
	process_sync_connections("cron")


def sync_lock(connection: str) -> Lock:
	"""The cache lock a sync of `connection` holds while it runs."""
	cache = cast(RedisWrapper, frappe.cache)
	return cache.lock(cache.make_key(sync_job_id(connection)), timeout=LOCK_TIMEOUT)


def run_connection_sync(connection: str) -> bool:
	"""Sync one Connection, unless another sync of it holds the lock. True when it ran."""
	from espresso_sync.espresso_sync.doctype.espresso_sync_connection.espresso_sync_connection import (
		get_connection,
	)

	lock = sync_lock(connection)
	if not lock.acquire(blocking=False):
		frappe.logger("espresso_sync").info(f"{connection}: a sync is already running")
		return False
	try:
		if not frappe.db.get_value(CONNECTION, connection, "pull_shot"):
			return False
		get_connection(connection).sync()
		return True
	finally:
		# a sync that outlived LOCK_TIMEOUT no longer owns it
		with suppress(LockError):
			lock.release()
