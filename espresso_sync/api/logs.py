# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""The portal's Sync log endpoints: what is failing, how much was synced each day, how long
the Pull Log is kept, and clearing it. Each is for System Managers only.

The entries themselves are read through the generic REST list: only what that cannot
answer is here. Nothing here returns an entry's payloads, so no answer carries a request,
a response or a document.
"""

import json
from datetime import date, datetime, timedelta
from typing import Any, cast

import frappe
from frappe import _
from frappe.query_builder import Criterion
from frappe.query_builder.functions import Count, Date
from frappe.utils import add_to_date, cint, get_datetime, getdate, now_datetime

PULL_LOG = "Espresso Sync Pull Log"
CONNECTION = "Espresso Sync Connection"
LOG_SETTINGS = "Log Settings"
LOGS_TO_CLEAR = "Logs To Clear"

MAX_FAILURES = 1000
MAX_ACTIVITY_DAYS = 30
MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 3650
# the periods the portal offers, as `since` may name them
PERIODS = {"1h": timedelta(hours=1), "24h": timedelta(hours=24), "7d": timedelta(days=7)}
# what clear_logs may filter on: the Pull Log field of each key, and the values it may have
CLEAR_FILTERS = {
	"sync_status": ("Success", "Failure"),
	"sync_direction": ("Import", "Export"),
	"sync_doctype": None,
	"transform": None,
	"before": None,
}


def check_connection_read(connection: str | None) -> None:
	"""Read on `connection`, or on the Connections when none is named."""
	if connection:
		frappe.get_doc(CONNECTION, connection).check_permission("read")
	else:
		frappe.has_permission(CONNECTION, "read", throw=True)


def datetime_argument(value: str, label: str) -> datetime:
	try:
		parsed = get_datetime(value)
	except ValueError, TypeError:
		parsed = None
	if not isinstance(parsed, datetime):
		frappe.throw(_("{0} is not a date or a time: {1}").format(label, str(value)[:100]))
	return cast("datetime", parsed)


def since_argument(since: str | None) -> datetime | None:
	"""`since` as a time: one of PERIODS back from now, or the date or time given. None for
	"attempt", which is each Connection's own last sync."""
	if not since or since == "attempt":
		return None
	if since in PERIODS:
		return now_datetime() - PERIODS[since]
	return datetime_argument(since, _("Since"))


def last_error(diagnostics: Any) -> tuple[str, str]:
	"""(code, message) of the diagnostic an entry failed with: its last error, which is the
	one the sync adds (see sync.failure). An entry without an error that has a code is
	"unknown", as the portal's lastError reads it: the Sync log filters by this code."""
	if isinstance(diagnostics, str):
		try:
			diagnostics = json.loads(diagnostics)
		except ValueError:
			diagnostics = None
	found = [d for d in diagnostics if isinstance(d, dict)] if isinstance(diagnostics, list) else []
	errors = [
		d for d in found if d.get("severity") == "error" and isinstance(d.get("code"), str) and d["code"]
	]
	if not errors:
		return "unknown", _("No error was logged")
	message = errors[-1].get("message")
	return errors[-1]["code"], message if isinstance(message, str) else ""


def attempt_cutoffs(connection: str | None) -> list[Criterion]:
	"""For each Connection, the entries of its last sync: those since its Last Sync Attempt,
	or all of them when it has none."""
	table = frappe.qb.DocType(PULL_LOG)
	criteria: list[Criterion] = []
	for row in frappe.get_all(
		CONNECTION,
		filters={"name": connection} if connection else {},
		fields=["name", "last_sync_attempt"],
	):
		criterion = table.sync_connection == row.name
		if row.last_sync_attempt:
			criterion = criterion & (table.creation >= row.last_sync_attempt)
		criteria.append(criterion)
	return criteria


@frappe.whitelist()
def failure_groups(
	connection: str | None = None, since: str | None = None, limit: int = 500
) -> dict[str, Any]:
	"""The failed entries, newest first, grouped by Connection, error code, transform and
	DocType: each group with how many there are and its latest entry. Without `since`, a
	Connection's failures are those of its last sync. At most `limit` entries are read:
	`truncated` says there were more."""
	frappe.only_for("System Manager")
	check_connection_read(connection)
	limit = min(max(cint(limit), 1), MAX_FAILURES)
	cutoff = since_argument(since)

	table = frappe.qb.DocType(PULL_LOG)
	query = (
		frappe.qb.from_(table)
		.select(
			table.name,
			table.creation,
			table.sync_connection,
			table.sync_doctype,
			table.sync_direction,
			table.transform,
			table.diagnostics,
		)
		.where(table.sync_status == "Failure")
		.orderby(table.creation, order=frappe.qb.desc)
		.orderby(table.name, order=frappe.qb.desc)
		# one more than is read, to know whether there are more
		.limit(limit + 1)
	)
	if cutoff:
		query = query.where(table.creation >= cutoff)
		if connection:
			query = query.where(table.sync_connection == connection)
	else:
		cutoffs = attempt_cutoffs(connection)
		if not cutoffs:
			return {"groups": [], "truncated": False}
		query = query.where(Criterion.any(cutoffs))
	rows = cast("list[Any]", query.run(as_dict=True))

	groups: dict[tuple[Any, ...], dict[str, Any]] = {}
	for row in rows[:limit]:
		code, message = last_error(row.diagnostics)
		key = (row.sync_connection, code, row.transform, row.sync_doctype, row.sync_direction)
		group = groups.get(key)
		if group:
			group["count"] += 1
			continue
		# the newest entry of the group comes first: its message stands for the group
		groups[key] = {
			"connection": row.sync_connection,
			"code": code,
			"message": message,
			"doctype": row.sync_doctype,
			"direction": row.sync_direction,
			"transform": row.transform,
			"count": 1,
			"latest": str(row.creation),
			"latest_log": row.name,
		}
	return {
		# the most frequent first; sorted() keeps the newest first among equals
		"groups": sorted(groups.values(), key=lambda group: -group["count"]),
		"truncated": len(rows) > limit,
	}


@frappe.whitelist()
def activity(connection: str | None = None, days: int = 7) -> list[dict[str, Any]]:
	"""For each of the last `days` days, today last: the documents imported, the documents
	exported, and the entries that failed. An entry of a request (it has no document) counts
	only when it failed. A day without entries is there with zeros."""
	frappe.only_for("System Manager")
	check_connection_read(connection)
	days = min(max(cint(days), 1), MAX_ACTIVITY_DAYS)
	today = cast("date", getdate())
	first = add_to_date(today, days=1 - days)
	buckets = {
		str(add_to_date(first, days=n)): {"imported": 0, "exported": 0, "failed": 0} for n in range(days)
	}

	table = frappe.qb.DocType(PULL_LOG)
	day = Date(table.creation)
	base = frappe.qb.from_(table).where(table.creation >= first)
	if connection:
		base = base.where(table.sync_connection == connection)

	failed = (
		base.select(day.as_("day"), Count(table.name).as_("entries"))
		.where(table.sync_status == "Failure")
		.groupby(day)
	)
	for row in cast("list[Any]", failed.run(as_dict=True)):
		if str(row.day) in buckets:
			buckets[str(row.day)]["failed"] = cint(row.entries)

	synced = (
		base.select(day.as_("day"), table.sync_direction, Count(table.name).as_("entries"))
		.where(table.sync_status == "Success")
		.where(table.sync_doc.isnotnull() & (table.sync_doc != ""))
		.groupby(day, table.sync_direction)
	)
	for row in cast("list[Any]", synced.run(as_dict=True)):
		if str(row.day) in buckets:
			key = "imported" if row.sync_direction == "Import" else "exported"
			buckets[str(row.day)][key] = cint(row.entries)

	return [{"date": day_of, **counts} for day_of, counts in buckets.items()]


def default_retention() -> int:
	"""The days hooks.py has Log Settings keep the Pull Log, until it is changed there."""
	days = frappe.get_hooks("default_log_clearing_doctypes", {}).get(PULL_LOG) or [30]
	return cint(days[-1])


def stored_retention() -> int:
	days = frappe.get_all(
		LOGS_TO_CLEAR,
		filters={"parenttype": LOG_SETTINGS, "parent": LOG_SETTINGS, "ref_doctype": PULL_LOG},
		pluck="days",
		limit=1,
	)
	return cint(days[0]) if days else default_retention()


@frappe.whitelist()
def get_retention() -> dict[str, int]:
	"""How many days Log Settings keeps a Pull Log entry."""
	frappe.only_for("System Manager")
	frappe.has_permission(LOG_SETTINGS, "read", throw=True)
	return {"days": stored_retention()}


@frappe.whitelist(methods=["POST"])
def set_retention(days: int) -> dict[str, int]:
	"""Have Log Settings keep a Pull Log entry for `days` days: its row there is changed, or
	added, and the other logs' rows are left as they are."""
	frappe.only_for("System Manager")
	days = cint(days)
	if not MIN_RETENTION_DAYS <= days <= MAX_RETENTION_DAYS:
		frappe.throw(_("Keep log entries for {0} to {1} days").format(MIN_RETENTION_DAYS, MAX_RETENTION_DAYS))
	settings = cast("Any", frappe.get_doc(LOG_SETTINGS))
	settings.check_permission("write")
	row = next((row for row in settings.logs_to_clear if row.ref_doctype == PULL_LOG), None)
	if row:
		row.days = days
	else:
		settings.append("logs_to_clear", {"ref_doctype": PULL_LOG, "days": days})
	# Log Settings announces the defaults it adds: that is the desk's news, not the caller's
	messages = len(frappe.local.message_log)
	settings.save()
	del frappe.local.message_log[messages:]
	return {"days": stored_retention()}


def clear_filters(filters: dict[str, Any] | str | None) -> dict[str, Any]:
	"""`filters` as Pull Log filters: only the keys of CLEAR_FILTERS, each with a value."""
	if isinstance(filters, str):
		try:
			filters = json.loads(filters)
		except ValueError:
			frappe.throw(_("Not JSON: {0}").format(filters[:100]))
	if filters is None:
		return {}
	if not isinstance(filters, dict):
		frappe.throw(_("The filters are not an object"))
	filters = cast("dict[str, Any]", filters)
	unknown = sorted(set(filters) - set(CLEAR_FILTERS))
	if unknown:
		frappe.throw(_("Log entries cannot be cleared by {0}").format(", ".join(unknown)))

	found: dict[str, Any] = {}
	for key, value in filters.items():
		if value is None or value == "":
			continue
		allowed = CLEAR_FILTERS[key]
		if not isinstance(value, str) or (allowed and value not in allowed):
			frappe.throw(_("{0} cannot be {1}").format(key, str(value)[:100]))
		if key == "before":
			found["creation"] = ("<", datetime_argument(value, _("Before")))
		else:
			found[key] = value
	return found


@frappe.whitelist(methods=["POST"])
def clear_logs(
	connection: str | None = None,
	filters: dict | str | None = None,
	confirm: str | None = None,
) -> dict[str, int]:
	"""Delete the Pull Log entries of `connection` that match `filters` (the status, the
	direction, the DocType, the transform, and `before`, a time); how many there were.
	Every entry of every Connection only with `confirm` "all". Nothing else is deleted: the
	synced documents and their Sync IDs stay."""
	frappe.only_for("System Manager")
	frappe.has_permission(PULL_LOG, "delete", throw=True)
	if connection:
		frappe.get_doc(CONNECTION, connection).check_permission("write")
	found = clear_filters(filters)
	if not connection and not found and confirm != "all":
		frappe.throw(_("Confirm with {0} to delete every log entry").format(frappe.bold("all")))
	if connection:
		found["sync_connection"] = connection

	# counted first: the delete does not say how many it took
	deleted = frappe.db.count(PULL_LOG, found)
	frappe.db.delete(PULL_LOG, found)
	return {"deleted": cint(deleted)}
