# Copyright (c) 2023, Avunu LLC and contributors
# For license information, please see license.txt

import base64
import json
from typing import cast
from urllib.parse import urlsplit

import frappe
from croniter import croniter
from frappe import _
from frappe.model.document import Document

from espresso_sync.scheduler import holding_sync_lock
from espresso_sync.sync import Run, ensure_sync_fields
from espresso_sync.utils.safe_fetch import credentials_apply, host_of, normalize_allowed_host

TRANSFORM = "Espresso Sync Transform"
SPEC = "Espresso Sync API Spec"
# a shot's transform Links, and the direction each must have
SHOT_TRANSFORMS = (
	("do_import", "import_transform", "Import"),
	("do_export", "export_transform", "Export"),
	("do_export", "update_transform", "Export"),
)


class EspressoSyncConnection(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from espresso_sync.espresso_sync.doctype.espresso_sync_connection_shot.espresso_sync_connection_shot import (
			EspressoSyncConnectionShot,
		)

		allowed_host: DF.Data | None
		api_key: DF.Data | None
		api_rate_limit: DF.Int
		api_secret: DF.Password | None
		auth_type: DF.Literal["Header-based", "Basic"]
		connection_name: DF.Data | None
		cron_rule: DF.Data | None
		enabled: DF.Check
		last_pull: DF.Datetime | None
		last_sync_attempt: DF.Datetime | None
		server_url: DF.Data
		shots: DF.Table[EspressoSyncConnectionShot]
		sync_frequency: DF.Literal["Manual", "Every Minute", "Hourly", "Daily", "Weekly", "Monthly", "Cron"]
	# end: auto-generated types

	def validate(self):
		# a share must not let anyone else change where the credentials are sent
		if not self.flags.ignore_permissions:
			frappe.only_for("System Manager")
		self.validate_cron_rule()
		self.validate_server_url()
		self.validate_shots()
		if self.enabled:
			for shot in self.shots:
				ensure_sync_fields(shot.dt)

	def validate_cron_rule(self):
		if self.sync_frequency != "Cron":
			return
		cron_rule = self.cron_rule or ""
		if not cron_rule:
			frappe.throw(_("A Cron Rule is needed when the Sync Frequency is Cron"))
		if not croniter.is_valid(cron_rule):
			frappe.throw(_("{0} is not a valid cron rule").format(frappe.bold(cron_rule)))

	def validate_server_url(self):
		"""The Server URL is http(s), and its host is the one the credentials may go to: the
		Allowed Host, filled from it when empty."""
		parts = urlsplit(self.server_url or "")
		if parts.scheme not in ("http", "https") or not parts.netloc:
			frappe.throw(
				_("{0} is not an http or https URL").format(frappe.bold(self.server_url or "")),
				title=_("Invalid Server URL"),
			)
		try:
			self.allowed_host = normalize_allowed_host(self.allowed_host) or host_of(self.server_url)
		except ValueError:
			frappe.throw(
				_("{0} is not a host: give a host name, or host:port, without a scheme or a path").format(
					frappe.bold(self.allowed_host or "")
				),
				title=_("Invalid Allowed Host"),
			)
		if not credentials_apply(self.server_url, self.allowed_host):
			frappe.throw(
				_("The Server URL's host {0} is not the Allowed Host {1}").format(
					frappe.bold(host_of(self.server_url)), frappe.bold(self.allowed_host or "")
				),
				title=_("Invalid Allowed Host"),
			)

	def validate_shots(self):
		"""Each shot syncs with Active transforms of its DocType, on this Connection's API Specs."""
		for shot in self.shots:
			for flag, fieldname in (("do_import", "import_transform"), ("do_export", "export_transform")):
				if shot.get(flag) and not shot.get(fieldname):
					frappe.throw(
						_("Row {0}: {1} is needed").format(shot.idx, _(shot.meta.get_label(fieldname)))
					)
			for flag, fieldname, direction in SHOT_TRANSFORMS:
				if shot.get(flag) and shot.get(fieldname):
					self.validate_transform(shot, shot.get(fieldname), direction)

	def validate_transform(self, shot, name: str, direction: str):
		transform = frappe.db.get_value(
			TRANSFORM, name, ["status", "direction", "document_type", "api_spec"], as_dict=True
		)
		if not transform or (transform.status, transform.direction, transform.document_type) != (
			"Active",
			direction,
			shot.dt,
		):
			frappe.throw(
				_("Row {0}: {1} is not an Active {2} transform of {3}").format(
					shot.idx, frappe.bold(name), _(direction), frappe.bold(shot.dt)
				)
			)
		if frappe.db.get_value(SPEC, transform.api_spec, "connection") != self.name:
			frappe.throw(
				_("Row {0}: {1} is on an API Spec of another Connection").format(shot.idx, frappe.bold(name))
			)

	def sync(self) -> int:
		"""Run every shot of the Connection; the number of failures logged."""
		run = Run(self)
		run.sync()
		return run.failures

	def get_credential_headers(self) -> dict[str, str]:
		"""The headers that carry the credentials: sent only to the Allowed Host."""
		secret = self.get_password("api_secret", raise_exception=False) or ""
		if self.auth_type == "Header-based" and self.api_key:
			return {self.api_key: secret}
		if self.auth_type == "Basic" and (self.api_key or secret):
			credentials = f"{self.api_key or ''}:{secret}"
			return {"Authorization": f"Basic {base64.b64encode(credentials.encode()).decode()}"}
		return {}


def get_connection(name: str) -> EspressoSyncConnection:
	return cast("EspressoSyncConnection", frappe.get_doc("Espresso Sync Connection", name))


@frappe.whitelist()
def sync_action(doc: str):
	return sync_now(json.loads(doc)["name"])


def sync_now(name: str) -> EspressoSyncConnection:
	"""Sync Now: sync the Connection in this request, unless a sync of it is running."""
	frappe.only_for("System Manager")
	connection = get_connection(name)
	connection.check_permission("write")
	# the lock the scheduled job holds: two syncs would both create the same new objects
	with holding_sync_lock(name) as acquired:
		if not acquired:
			frappe.throw(
				_("A sync of {0} is already running").format(frappe.bold(name)), title=_("Sync Running")
			)
		failures = connection.sync()
	if failures:
		frappe.msgprint(
			_("{0} failed: see the Espresso Sync Pull Log").format(failures),
			indicator="orange",
			alert=True,
		)
	return connection
