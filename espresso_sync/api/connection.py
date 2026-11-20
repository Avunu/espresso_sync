# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""The Connection endpoints of the portal: the status of every Connection, one Connection
without its secret, making and saving one, Sync Now and Resync, pausing, a test request, a cron preview, the
shots, and deleting. Each is for System Managers only.

No answer holds the API Secret, its mask, a credential header or a response body: the
secret is written by create_connection and save_connection, and never read back."""

import json
import time
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit

import frappe
import requests
from croniter import CroniterBadDateError, croniter
from frappe import _
from frappe.query_builder.functions import Count
from frappe.rate_limiter import rate_limit
from frappe.utils import cint, now_datetime
from frappe.utils.background_jobs import is_job_enqueued

from espresso_sync.espresso_sync.doctype.espresso_sync_connection import espresso_sync_connection as esc
from espresso_sync.redaction import connection_secrets, redact_text
from espresso_sync.scheduler import (
	cron_next,
	enqueue_connection_sync,
	holding_sync_lock,
	last_run,
	sync_job_id,
	sync_lock,
)
from espresso_sync.sync import SHOT
from espresso_sync.utils.safe_fetch import credentials_apply, host_of, safe_request

CONNECTION = "Espresso Sync Connection"
SPEC = "Espresso Sync API Spec"
TRANSFORM = "Espresso Sync Transform"
PULL_LOG = "Espresso Sync Pull Log"
SYNC_ID = "Espresso Sync ID"

# what the portal may set on a Connection, besides its API Secret: never Enabled, which
# set_enabled sets, nor the shots, which have endpoints that hold the sync lock
CONNECTION_FIELDS = (
	"server_url",
	"allowed_host",
	"auth_type",
	"api_key",
	"sync_frequency",
	"cron_rule",
	"api_rate_limit",
)
# what the portal may set on a shot (and its DocType, when the shot is added): never
# Last Import and Last Export, which only a sync and a reset write
SHOT_FLAGS = ("do_import", "do_export")
SHOT_LINKS = ("import_transform", "export_transform", "update_transform", "follow_up_transform")
SHOT_WATERMARKS = {
	"Import": ("last_import",),
	"Export": ("last_export",),
	"Both": ("last_import", "last_export"),
}
# (connect, read) seconds of the test request: a person is waiting for it
CHECK_TIMEOUT = (10, 30)
MAX_ERROR_LENGTH = 300
MAX_CRON_PREVIEW = 10


def as_text(value: Any) -> str | None:
	"""A datetime as the JSON response would write it, so a caller in Python reads the same."""
	return str(value) if value else None


def get_doc(connection: str, ptype: str = "read") -> esc.EspressoSyncConnection:
	doc = esc.get_connection(connection)
	doc.check_permission(ptype)
	return doc


def sync_state(connection: str) -> str:
	"""running while a sync holds the Connection's lock, queued while its job waits (or has
	started and not taken the lock yet), idle otherwise."""
	if sync_lock(connection).locked():
		return "running"
	if is_job_enqueued(sync_job_id(connection)):
		return "queued"
	return "idle"


def last_error(diagnostics: Any) -> tuple[str, str]:
	"""The code and message of the last error among a Pull Log's diagnostics (the last
	diagnostic when none is an error)."""
	try:
		entries = json.loads(diagnostics) if isinstance(diagnostics, str) else diagnostics
	except ValueError:
		entries = None
	entries = (
		[entry for entry in entries or [] if isinstance(entry, dict)] if isinstance(entries, list) else []
	)
	if not entries:
		return "", ""
	errors = [entry for entry in entries if entry.get("severity") == "error"]
	entry = (errors or entries)[-1]
	return str(entry.get("code") or ""), str(entry.get("message") or "")[:MAX_ERROR_LENGTH]


def shot_problems(shots: list[Any], transforms: dict[str, Any], specs: dict[str, Any]) -> dict[str, list]:
	"""What the Connection's validation would refuse on each shot, by Connection: the same
	checks, read without throwing, as a transform can stop being Active after the shot is saved."""
	problems: dict[str, list] = {}

	def add(shot: Any, code: str, message: str, transform: str | None):
		problem = {"code": code, "message": message, "doctype": shot.dt, "transform": transform}
		found = problems.setdefault(shot.parent, [])
		# once, for a transform the shot names in two of its fields
		if problem not in found:
			found.append(problem)

	for shot in shots:
		for flag, fieldname in (("do_import", "import_transform"), ("do_export", "export_transform")):
			if shot.get(flag) and not shot.get(fieldname):
				direction = _("an import") if flag == "do_import" else _("an export")
				add(
					shot,
					"missing-transform",
					_("{0} has no transform for {1}").format(shot.dt, direction),
					None,
				)
		for flag, fieldname, direction in esc.SHOT_TRANSFORMS:
			name = shot.get(fieldname)
			if not (shot.get(flag) and name):
				continue
			transform = transforms.get(name)
			if not transform:
				add(shot, "missing-transform", _("{0} does not exist").format(name), name)
			elif transform.status != "Active":
				add(shot, "transform-not-active", _("{0} is not Active").format(name), name)
			elif transform.direction != direction:
				message = _("{0} is not an {1} transform").format(name, _(direction))
				add(shot, "transform-direction", message, name)
			elif transform.document_type != shot.dt:
				add(shot, "transform-doctype", _("{0} is not a transform of {1}").format(name, shot.dt), name)
			elif specs.get(transform.api_spec) != shot.parent:
				message = _("{0} is on an API Spec of another Connection").format(name)
				add(shot, "transform-connection", message, name)
	return problems


def counts_since(names: list[str], since: datetime) -> dict[tuple[str, str], int]:
	"""What the Pull Log holds since `since`, by (Connection, status): the entries that
	failed, and the documents synced. A request that succeeded synced no document, so its
	entry is not counted (as api.logs.activity has it)."""
	if not names:
		return {}
	log = frappe.qb.DocType(PULL_LOG)
	rows = (
		frappe.qb.from_(log)
		.select(log.sync_connection, log.sync_status, Count("*"))
		.where(log.sync_connection.isin(names))
		.where(log.creation >= since)
		.where((log.sync_status == "Failure") | (log.sync_doc.isnotnull() & (log.sync_doc != "")))
		.groupby(log.sync_connection, log.sync_status)
	).run()
	return {(row[0], row[1]): cint(row[2]) for row in rows}


def last_failure(connection: str) -> dict[str, Any] | None:
	rows = frappe.get_all(
		PULL_LOG,
		filters={"sync_connection": connection, "sync_status": "Failure"},
		fields=["name", "creation", "diagnostics"],
		order_by="creation desc, name desc",
		limit=1,
	)
	if not rows:
		return None
	code, message = last_error(rows[0].diagnostics)
	return {"name": rows[0].name, "creation": as_text(rows[0].creation), "code": code, "message": message}


def next_run(row: Any) -> str | None:
	"""When the scheduler next finds the Connection's Cron Rule due: in the past when it is
	overdue. None for any other frequency, and for a Connection that is not Enabled."""
	if not row.enabled or row.sync_frequency != "Cron":
		return None
	return as_text(cron_next(row.cron_rule, last_run(row)))


def status_rows(connection: str | None = None) -> list[dict[str, Any]]:
	rows = frappe.get_all(
		CONNECTION,
		filters={"name": connection} if connection else {},
		fields=[
			"name",
			"enabled",
			"server_url",
			"sync_frequency",
			"cron_rule",
			"last_pull",
			"last_sync_attempt",
			"creation",
		],
		order_by="name asc",
	)
	names = [row.name for row in rows]
	shots = (
		frappe.get_all(
			SHOT,
			filters={"parenttype": CONNECTION, "parent": ("in", names)},
			fields=["parent", "idx", "dt", *SHOT_FLAGS, *SHOT_LINKS],
			order_by="parent asc, idx asc",
		)
		if names
		else []
	)
	transform_names = {shot.get(fieldname) for shot in shots for fieldname in SHOT_LINKS} - {None, ""}
	transforms = (
		{
			transform.name: transform
			for transform in frappe.get_all(
				TRANSFORM,
				filters={"name": ("in", sorted(transform_names))},
				fields=["name", "status", "direction", "document_type", "api_spec"],
			)
		}
		if transform_names
		else {}
	)
	transform_specs = sorted({transform.api_spec for transform in transforms.values() if transform.api_spec})
	specs = (
		{
			spec.name: spec.connection
			for spec in frappe.get_all(
				SPEC, filters={"name": ("in", transform_specs)}, fields=["name", "connection"]
			)
		}
		if transform_specs
		else {}
	)
	problems = shot_problems(shots, transforms, specs)
	last_day = counts_since(names, now_datetime() - timedelta(hours=24))
	answer = []
	for row in rows:
		last_run_counts = counts_since([row.name], row.last_sync_attempt) if row.last_sync_attempt else {}
		answer.append(
			{
				"name": row.name,
				"enabled": 1 if row.enabled else 0,
				"server_url": row.server_url,
				"sync_frequency": row.sync_frequency,
				"cron_rule": row.cron_rule,
				"last_pull": as_text(row.last_pull),
				"last_sync_attempt": as_text(row.last_sync_attempt),
				"state": sync_state(row.name),
				"next_run": next_run(row),
				"shots": len([shot for shot in shots if shot.parent == row.name]),
				"problems": problems.get(row.name, []),
				"failures_last_run": last_run_counts.get((row.name, "Failure"), 0),
				"successes_last_run": last_run_counts.get((row.name, "Success"), 0),
				"failures_24h": last_day.get((row.name, "Failure"), 0),
				"successes_24h": last_day.get((row.name, "Success"), 0),
				"last_failure": last_failure(row.name),
			}
		)
	return answer


def status_row(connection: str) -> dict[str, Any]:
	return status_rows(connection)[0]


def shot_values(doc: esc.EspressoSyncConnection) -> list[dict[str, Any]]:
	return [
		{
			"name": shot.name,
			"idx": shot.idx,
			"dt": shot.dt,
			"do_import": 1 if shot.do_import else 0,
			"import_transform": shot.import_transform,
			"last_import": as_text(shot.last_import),
			"do_export": 1 if shot.do_export else 0,
			"export_transform": shot.export_transform,
			"update_transform": shot.update_transform,
			"follow_up_transform": shot.follow_up_transform,
			"last_export": as_text(shot.last_export),
		}
		for shot in doc.shots
	]


def shots_answer(doc: esc.EspressoSyncConnection) -> dict[str, Any]:
	return {"modified": as_text(doc.modified), "shots": shot_values(doc)}


def find_shot(doc: esc.EspressoSyncConnection, name: str) -> Any:
	"""The shot row `name` of the Connection: a row of another Connection is not found."""
	for shot in doc.shots:
		if shot.name == name:
			return shot
	frappe.throw(_("{0} has no shot {1}").format(doc.name, name), title=_("Not Found"))
	raise frappe.ValidationError


def number_shots(doc: esc.EspressoSyncConnection):
	for index, shot in enumerate(doc.shots):
		shot.idx = index + 1


def read_watermarks(doc: esc.EspressoSyncConnection):
	"""Set Last Import and Last Export of the shots to what is stored now. Read locking the
	rows: that reads what a sync committed after this request began, and waits for a sync
	that let its lock go and has not committed yet. Saving the Connection writes every field
	of its shots, and would otherwise write these back as they were when it was loaded."""
	names = [shot.name for shot in doc.shots if shot.name]
	if not names:
		return
	table = frappe.qb.DocType(SHOT)
	rows = (
		frappe.qb.from_(table)
		.select(table.name, table.last_import, table.last_export)
		.where(table.name.isin(names))
		.for_update()
		.run(as_dict=True)
	)
	stored = {row.name: row for row in cast("list[Any]", rows)}
	for shot in doc.shots:
		if shot.name in stored:
			shot.last_import = stored[shot.name].last_import
			shot.last_export = stored[shot.name].last_export


@contextmanager
def changing_shots(connection: str) -> Generator[esc.EspressoSyncConnection]:
	"""The Connection, to change its shots, while no sync of it runs: a sync writes Last
	Import and Last Export on the rows it read when it began. What was changed is committed
	before the lock is let go, so the sync it lets in reads it."""
	with holding_sync_lock(connection) as acquired:
		if not acquired:
			frappe.throw(_("{0} is syncing: change its shots when it is done").format(connection))
		doc = get_doc(connection, "write")
		read_watermarks(doc)
		yield doc
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- the change must be seen by the sync the lock lets in


def spec_names(connection: str) -> list[str]:
	return frappe.get_all(SPEC, filters={"connection": connection}, pluck="name", order_by="name asc")


def first_auth_hint(specs: list[str]) -> dict[str, Any] | None:
	"""What the Connection's first API Spec that suggests an authentication suggests: a hint
	its spec requires before one it only declares."""
	for name in specs:
		stored = json.loads(frappe.db.get_value(SPEC, name, "auth_hints") or "[]")
		hints = (
			[hint for hint in stored if isinstance(hint, dict) and hint.get("suggestion")]
			if isinstance(stored, list)
			else []
		)
		hints.sort(key=lambda hint: not hint.get("required"))
		if hints:
			suggestion = hints[0]["suggestion"]
			return {
				"spec": name,
				"scheme": hints[0].get("scheme"),
				"note": hints[0].get("note"),
				"auth_type": suggestion.get("auth_type"),
				"api_key": suggestion.get("api_key"),
			}
	return None


def connection_values(values: dict | str, *more: str) -> dict[str, Any]:
	"""`values` as the fields of a Connection the portal may set: CONNECTION_FIELDS, the API
	Secret and `more`. Any other is refused, not left out: it was not saved."""
	found = frappe.parse_json(values) if isinstance(values, str) else values
	if not isinstance(found, dict):
		frappe.throw(_("The values of a Connection are an object of its fields"))
	found = cast("dict[str, Any]", found)
	unknown = sorted(set(found) - {*CONNECTION_FIELDS, "api_secret", *more})
	if unknown:
		frappe.throw(_("{0} cannot be set here").format(", ".join(unknown)))
	return dict(found)


def check_url(server_url: str, path: str | None) -> str:
	"""The URL of the test request: the Server URL, or a path (with its query, if any) under
	it. What reads as naming another host (`//`, a backslash, a URL) is refused, and the
	path is joined to the Server URL's own, so the host is the Server URL's whatever it says."""
	path = (path or "").strip()
	if not path:
		return server_url
	if "\\" in path or path.startswith("//") or urlsplit(path).netloc:
		frappe.throw(
			_("{0} is not a path under the Server URL").format(frappe.bold(path)), title=_("Invalid Path")
		)
	base = urlsplit(server_url)
	# split by hand: a first segment with a colon (`items:search`) is no scheme here
	added, _mark, query = path.partition("#")[0].partition("?")
	joined = f"{base.path.rstrip('/')}/{added.lstrip('/')}"
	return urlunsplit((base.scheme, base.netloc, joined, "&".join(filter(None, (base.query, query))), ""))


def verdict_of(status: int) -> str:
	if status < 400:
		return "ok"
	if status in (401, 403):
		return "auth"
	return "reachable" if status < 500 else "error"


@frappe.whitelist(methods=["GET"])
def list_status(connection: str | None = None) -> dict[str, Any]:
	"""How every Connection (or `connection`) is doing: whether it is syncing, what its last
	sync and the last 24 hours logged, and what is wrong with its shots."""
	frappe.only_for("System Manager")
	if connection:
		get_doc(connection)
	else:
		frappe.has_permission(CONNECTION, "read", throw=True)
	return {"now": as_text(now_datetime()), "connections": status_rows(connection)}


@frappe.whitelist(methods=["GET"])
def get_connection(connection: str) -> dict[str, Any]:
	"""The Connection for the portal: everything but the API Secret, of which only whether
	one is stored is said."""
	frappe.only_for("System Manager")
	doc = get_doc(connection)
	specs = spec_names(connection)
	transforms = {"api_spec": ("in", specs)}
	return {
		"name": doc.name,
		"modified": as_text(doc.modified),
		"enabled": 1 if doc.enabled else 0,
		"server_url": doc.server_url,
		"allowed_host": doc.allowed_host,
		"auth_type": doc.auth_type,
		"api_key": doc.api_key,
		"sync_frequency": doc.sync_frequency,
		"cron_rule": doc.cron_rule,
		"api_rate_limit": doc.api_rate_limit,
		"last_pull": as_text(doc.last_pull),
		"last_sync_attempt": as_text(doc.last_sync_attempt),
		"has_secret": bool(doc.get_password("api_secret", raise_exception=False)),
		"shots": shot_values(doc),
		"setup": {
			"specs": len(specs),
			"transforms": frappe.db.count(TRANSFORM, transforms) if specs else 0,
			"active_transforms": (
				frappe.db.count(TRANSFORM, {**transforms, "status": "Active"}) if specs else 0
			),
		},
		"auth_hints": first_auth_hint(specs),
	}


@frappe.whitelist(methods=["POST"])
def create_connection(values: dict | str) -> dict[str, Any]:
	"""Make a Connection of `values` (its name as `connection_name`), paused, and Manual
	unless they say when it syncs. Answered as get_connection answers: the REST API answers
	an insert with the document, in which the API Secret is a mask as long as it is."""
	frappe.only_for("System Manager")
	fields = connection_values(values, "connection_name")
	doc = frappe.new_doc(CONNECTION)
	doc.update({"sync_frequency": "Manual", **fields, "enabled": 0})
	doc.insert()
	return get_connection(str(doc.name))


@frappe.whitelist(methods=["POST"])
def save_connection(connection: str, values: dict | str, modified: str | None = None) -> dict[str, Any]:
	"""Save the Connection's settings: those of CONNECTION_FIELDS that `values` has. The API
	Secret stays as it is when `values` has none, is removed by an empty one, and is set by
	any other. Refused when the Connection is no longer as it was at `modified`. Answered as
	get_connection answers, and not with the saved document as the REST API does."""
	frappe.only_for("System Manager")
	doc = get_doc(connection, "write")
	fields = connection_values(values)
	if modified and as_text(doc.modified) != modified:
		frappe.throw(
			_("{0} was changed since this page read it: reload the page to see how").format(connection),
			frappe.TimestampMismatchError,
		)
	doc.update(fields)
	doc.save()
	return get_connection(connection)


@frappe.whitelist(methods=["POST"])
def sync_now(connection: str) -> dict[str, Any]:
	"""Queue the job a scheduled sync runs, unless one is queued or running. Refused for a
	Connection that is not Enabled, whose job would do nothing."""
	frappe.only_for("System Manager")
	doc = get_doc(connection, "write")
	if not doc.enabled:
		frappe.throw(_("{0} is not Enabled: enable it to sync").format(connection))
	enqueue_connection_sync(connection)
	return status_row(connection)


@frappe.whitelist(methods=["POST"])
def resync(connection: str) -> dict[str, Any]:
	"""Forget when each shot last imported and exported, and queue a sync (see the
	Connection's resync). Refused while the Connection syncs."""
	frappe.only_for("System Manager")
	get_doc(connection, "write")
	shown = len(frappe.local.message_log)
	esc.resync(connection)
	# the desk's alert: the portal says it itself
	del frappe.local.message_log[shown:]
	return status_row(connection)


@frappe.whitelist(methods=["POST"])
def set_enabled(connection: str, enabled: int) -> dict[str, Any]:
	"""Enable the Connection, through its validation, or pause it, without: a Connection
	whose transform is no longer Active cannot be saved, and must still be paused."""
	frappe.only_for("System Manager")
	doc = get_doc(connection, "write")
	if cint(enabled):
		doc.enabled = 1
		doc.save()
	else:
		frappe.db.set_value(CONNECTION, connection, "enabled", 0)
	return status_row(connection)


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=10, seconds=60)
def check_connection(connection: str, path: str | None = None) -> dict[str, Any]:
	"""Send one GET to the saved Server URL (or `path` under it) with the saved credentials,
	which go to the Allowed Host only, and say how it was answered: never with what."""
	frappe.only_for("System Manager")
	doc = get_doc(connection, "write")
	url = check_url(doc.server_url, path)
	credentials = doc.get_credential_headers()
	answer: dict[str, Any] = {
		"ok": False,
		"verdict": "unreachable",
		"status": None,
		"reason": None,
		"elapsed_ms": 0,
		"host": host_of(url),
		"credentials_sent": bool(credentials) and credentials_apply(url, doc.allowed_host),
		"error": None,
	}
	began = time.monotonic()
	try:
		response = safe_request(
			"GET",
			url,
			headers={"Accept": "application/json, */*;q=0.5"},
			credentials=credentials,
			allowed_host=doc.allowed_host,
			timeout=CHECK_TIMEOUT,
		)
	except requests.RequestException as e:
		header_names, secrets = connection_secrets(connection)
		error = redact_text(str(e), secrets, header_names) or type(e).__name__
		answer["error"] = error[:MAX_ERROR_LENGTH]
	else:
		verdict = verdict_of(response.status_code)
		answer.update(
			{
				"ok": verdict == "ok",
				"verdict": verdict,
				"status": response.status_code,
				"reason": response.reason or None,
			}
		)
	answer["elapsed_ms"] = int((time.monotonic() - began) * 1000)
	return answer


@frappe.whitelist(methods=["GET"])
def cron_preview(cron_rule: str, count: int = 3) -> dict[str, Any]:
	"""The next `count` (1 to 10) times `cron_rule` fires, in the site's time."""
	frappe.only_for("System Manager")
	cron_rule = (cron_rule or "").strip()
	if not cron_rule or not croniter.is_valid(cron_rule):
		return {"valid": False, "next": []}
	times = croniter(cron_rule, now_datetime())
	count = min(max(cint(count), 1), MAX_CRON_PREVIEW)
	try:
		return {"valid": True, "next": [str(times.get_next(datetime)) for _index in range(count)]}
	except CroniterBadDateError:
		# a rule that reads as one and never fires: the 30th of February
		return {"valid": False, "next": []}


@frappe.whitelist(methods=["GET"])
def shot_options(connection: str) -> list[dict[str, Any]]:
	"""The transforms a shot of the Connection can name: those on its API Specs, the Draft
	ones included (a shot cannot be saved with one, and the portal says why)."""
	frappe.only_for("System Manager")
	get_doc(connection)
	specs = spec_names(connection)
	if not specs:
		return []
	return [
		dict(row)
		for row in frappe.get_all(
			TRANSFORM,
			filters={"api_spec": ("in", specs)},
			fields=["name", "direction", "document_type", "status", "api_spec"],
			order_by="name asc",
		)
	]


@frappe.whitelist(methods=["POST"])
def save_shot(connection: str, shot: dict | str, name: str | None = None) -> dict[str, Any]:
	"""Add a shot, or change the shot `name`: what it imports and exports, and with which
	transforms. Its DocType is set when it is added only, and Last Import and Last Export
	never."""
	frappe.only_for("System Manager")
	values = frappe.parse_json(shot) if isinstance(shot, str) else shot
	if not isinstance(values, dict):
		frappe.throw(_("A shot is an object of its fields"))
	changes: dict[str, Any] = {key: 1 if cint(values[key]) else 0 for key in SHOT_FLAGS if key in values}
	changes.update({key: values[key] or None for key in SHOT_LINKS if key in values})
	with changing_shots(connection) as doc:
		if name:
			find_shot(doc, name).update(changes)
		else:
			doctype = str(values.get("dt") or "").strip()
			if not doctype:
				frappe.throw(_("A shot needs a DocType"))
			if any(row.dt == doctype for row in doc.shots):
				frappe.throw(_("{0} already has a shot for {1}").format(connection, doctype))
			doc.append("shots", {"dt": doctype, **changes})
		doc.save()
		return shots_answer(doc)


@frappe.whitelist(methods=["POST"])
def remove_shot(connection: str, name: str) -> dict[str, Any]:
	"""Remove the shot `name`. The documents it synced, and their Sync tab, stay."""
	frappe.only_for("System Manager")
	with changing_shots(connection) as doc:
		doc.remove(find_shot(doc, name))
		number_shots(doc)
		doc.save()
		return shots_answer(doc)


@frappe.whitelist(methods=["POST"])
def move_shot(connection: str, name: str, by: int) -> dict[str, Any]:
	"""Move the shot `name` one place up (-1) or down (1): a sync runs the shots in order."""
	frappe.only_for("System Manager")
	by = cint(by)
	if by not in (-1, 1):
		frappe.throw(_("A shot moves one place up or down"))
	with changing_shots(connection) as doc:
		index = doc.shots.index(find_shot(doc, name))
		if not 0 <= index + by < len(doc.shots):
			frappe.throw(_("{0} cannot move further").format(doc.shots[index].dt))
		doc.shots.insert(index + by, doc.shots.pop(index))
		number_shots(doc)
		doc.save()
		return shots_answer(doc)


@frappe.whitelist(methods=["POST"])
def reset_shot(connection: str, name: str, direction: str) -> dict[str, Any]:
	"""Forget when the shot `name` last imported, exported, or both, so that its next sync
	reads or sends everything again. Nothing is queued."""
	frappe.only_for("System Manager")
	if direction not in SHOT_WATERMARKS:
		frappe.throw(_("{0} is not Import, Export or Both").format(direction))
	with changing_shots(connection) as doc:
		shot = find_shot(doc, name)
		frappe.db.set_value(SHOT, shot.name, dict.fromkeys(SHOT_WATERMARKS[direction]), update_modified=False)
	doc.reload()
	return {"shots": shot_values(doc)}


@frappe.whitelist(methods=["GET"])
def delete_impact(connection: str) -> dict[str, Any]:
	"""What deleting the Connection removes (its log entries, its documents' links), and
	what keeps it from being deleted (its API Specs, a sync)."""
	frappe.only_for("System Manager")
	get_doc(connection)
	specs = spec_names(connection)
	return {
		"specs": specs,
		"transforms": frappe.db.count(TRANSFORM, {"api_spec": ("in", specs)}) if specs else 0,
		"logs": frappe.db.count(PULL_LOG, {"sync_connection": connection}),
		"links": frappe.db.count(SYNC_ID, {"sync_connection": connection}),
		"state": sync_state(connection),
	}


@frappe.whitelist(methods=["POST"])
def delete_connection(connection: str, confirm: str) -> dict[str, Any]:
	"""Delete the Connection, its Pull Log and the links of its documents (their Espresso
	Sync ID rows). The documents and their Sync tab stay. `confirm` is the Connection's name.
	Refused while it syncs, and while it has API Specs: those, and their transforms, go first."""
	frappe.only_for("System Manager")
	doc = get_doc(connection, "write")
	doc.check_permission("delete")
	if confirm != doc.name:
		frappe.throw(_("Type {0} to delete it").format(doc.name), title=_("Not Deleted"))
	with holding_sync_lock(connection) as acquired:
		if not acquired or is_job_enqueued(sync_job_id(connection)):
			frappe.throw(
				_("{0} is syncing: delete it when it is done").format(connection), title=_("Not Deleted")
			)
		specs = spec_names(connection)
		if specs:
			frappe.throw(
				_("{0} has API Specs: delete them first ({1})").format(connection, ", ".join(specs)),
				title=_("Not Deleted"),
			)
		frappe.db.delete(PULL_LOG, {"sync_connection": connection})
		frappe.db.delete(SYNC_ID, {"sync_connection": connection})
		frappe.delete_doc(CONNECTION, connection)
	return {"deleted": True}
