# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""The portal's linked documents: the Espresso Sync ID rows that tie a document to what it
is in a Connection's API. Each endpoint is for System Managers only.

A row is a child of the document it links, and a sync exports the documents modified since
the last one. So every change here writes the row alone and leaves the document's
`modified` as it is: saving the document instead would send it out again.
"""

from typing import Any, cast

import frappe
from frappe import _
from frappe.query_builder import Criterion
from frappe.query_builder.functions import Count, Max
from frappe.utils import cint

from espresso_sync.sync import SYNC_ID, SYNC_IDS_FIELD

CONNECTION = "Espresso Sync Connection"
MAX_PAGE = 100
LINK_FIELDS = (
	"name",
	"parenttype",
	"parent",
	"external_id",
	"last_synced_modified",
	"external_modified",
	"dont_sync",
)


def check_connection(connection: str, ptype: str) -> None:
	frappe.get_doc(CONNECTION, connection).check_permission(ptype)


def check_document(doctype: str, name: str) -> None:
	"""Write on the document a link is a row of. Refused as a validation error, which the
	portal shows: it takes a 403 for a session that ended, and loads the page again."""
	if not frappe.has_permission(doctype, "write", name):
		frappe.throw(
			_("You may not change {0} {1}, so not its link either").format(_(doctype), frappe.bold(name)),
			title=_("Not Permitted"),
		)


def as_link(row: Any) -> dict[str, Any]:
	return {
		"name": row.name,
		"parenttype": row.parenttype,
		"parent": row.parent,
		"external_id": row.external_id or None,
		"last_synced_modified": str(row.last_synced_modified) if row.last_synced_modified else None,
		"external_modified": str(row.external_modified) if row.external_modified else None,
		"dont_sync": 1 if row.dont_sync else 0,
	}


def read_link(name: str) -> dict[str, Any]:
	row = frappe.db.get_value(SYNC_ID, name, LINK_FIELDS, as_dict=True)
	return as_link(row)


def writable_link(name: str) -> Any:
	"""The row `name`, for a user who may change both ends of it: its Connection, and the
	document it is a row of."""
	row = frappe.db.get_value(SYNC_ID, name, [*LINK_FIELDS, "sync_connection"], as_dict=True)
	if not row:
		frappe.throw(_("There is no linked document {0}").format(name), frappe.DoesNotExistError)
	row = cast("Any", row)
	check_connection(row.sync_connection, "write")
	check_document(row.parenttype, row.parent)
	return row


def write_link(row: Any, values: dict[str, Any]) -> dict[str, Any]:
	"""Set `values` on the row, and on nothing else: neither it nor its document is stamped
	as modified."""
	frappe.db.set_value(SYNC_ID, row.name, values, update_modified=False)
	frappe.clear_document_cache(row.parenttype, row.parent)
	return read_link(row.name)


def check_external_id(connection: str, doctype: str, external_id: str, row: str | None = None) -> None:
	"""No other document of `doctype` is `external_id` in the Connection's API: an import
	finds the document to update by it."""
	taken = frappe.get_all(
		SYNC_ID,
		filters={
			"sync_connection": connection,
			"parenttype": doctype,
			"external_id": external_id,
			"name": ("!=", row or ""),
		},
		pluck="parent",
		limit=1,
	)
	if taken:
		frappe.throw(
			_("{0} {1} is already linked to {2}").format(
				_(doctype), frappe.bold(taken[0]), frappe.bold(external_id)
			)
		)


def like_pattern(search: str) -> str:
	"""`search` as a LIKE pattern that matches it anywhere, its own wildcards taken literally."""
	escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
	return f"%{escaped}%"


@frappe.whitelist()
def list_links(
	connection: str,
	doctype: str | None = None,
	search: str | None = None,
	not_syncing: int = 0,
	start: int = 0,
	limit: int = 50,
) -> dict[str, Any]:
	"""A page of the documents linked on the Connection: those of `doctype`, whose name or
	External ID contains `search`, and with `not_syncing` only those set not to sync. With
	how many match in all, and the DocTypes the Connection has links of."""
	frappe.only_for("System Manager")
	check_connection(connection, "read")
	start = max(cint(start), 0)
	limit = min(max(cint(limit), 1), MAX_PAGE)

	table = frappe.qb.DocType(SYNC_ID)
	of_connection = table.sync_connection == connection
	criteria: list[Criterion] = [of_connection]
	if doctype:
		criteria.append(table.parenttype == doctype)
	if search and search.strip():
		pattern = like_pattern(search.strip())
		criteria.append(table.external_id.like(pattern) | table.parent.like(pattern))
	if cint(not_syncing):
		criteria.append(table.dont_sync == 1)
	matching = Criterion.all(criteria)

	rows = (
		frappe.qb.from_(table)
		.select(*(table[field] for field in LINK_FIELDS))
		.where(matching)
		.orderby(table.parenttype)
		.orderby(table.parent)
		.orderby(table.name)
		.limit(limit)
		.offset(start)
		.run(as_dict=True)
	)
	total = frappe.qb.from_(table).select(Count(table.name)).where(matching).run()
	doctypes = (
		frappe.qb.from_(table)
		.select(table.parenttype)
		.distinct()
		.where(of_connection)
		.orderby(table.parenttype)
		.run(pluck=True)
	)
	return {
		"rows": [as_link(row) for row in cast("list[Any]", rows)],
		"total": cint(total[0][0]) if total else 0,
		"doctypes": list(doctypes),
	}


@frappe.whitelist(methods=["POST"])
def add_link(connection: str, doctype: str, docname: str, external_id: str) -> dict[str, Any]:
	"""Link the document to `external_id` in the Connection's API, as an import or an export
	would have: the next sync updates the two instead of creating one of them again. For a
	DocType with the Sync tab (a shot of an Enabled Connection adds it), and a document the
	Connection has no link of yet."""
	frappe.only_for("System Manager")
	check_connection(connection, "write")
	external_id = (external_id or "").strip()
	if not external_id:
		frappe.throw(_("An External ID is needed"))
	if not frappe.db.exists("DocType", doctype) or not frappe.get_meta(doctype).has_field(SYNC_IDS_FIELD):
		frappe.throw(
			_("{0} has no Sync tab: add a shot for it to an Enabled Connection first").format(
				frappe.bold(doctype)
			)
		)
	if not frappe.db.exists(doctype, docname):
		frappe.throw(
			_("There is no {0} {1}").format(_(doctype), frappe.bold(docname)), frappe.DoesNotExistError
		)
	check_document(doctype, docname)
	if frappe.db.exists(SYNC_ID, {"sync_connection": connection, "parenttype": doctype, "parent": docname}):
		frappe.throw(
			_("{0} {1} is already linked on {2}").format(
				_(doctype), frappe.bold(docname), frappe.bold(connection)
			)
		)
	check_external_id(connection, doctype, external_id)

	table = frappe.qb.DocType(SYNC_ID)
	last = (
		frappe.qb.from_(table)
		.select(Max(table.idx))
		.where((table.parenttype == doctype) & (table.parent == docname))
		.where(table.parentfield == SYNC_IDS_FIELD)
		.run()
	)
	row = frappe.new_doc(SYNC_ID)
	row.update(
		{
			"parenttype": doctype,
			"parent": docname,
			"parentfield": SYNC_IDS_FIELD,
			"idx": cint(last[0][0] if last else 0) + 1,
			"sync_connection": connection,
			"external_id": external_id,
		}
	)
	# the row alone: inserting through the document would stamp it modified, and export it
	row.db_insert()
	frappe.clear_document_cache(doctype, docname)
	return read_link(str(row.name))


@frappe.whitelist(methods=["POST"])
def update_link(name: str, external_id: str | None = None, dont_sync: int | None = None) -> dict[str, Any]:
	"""Change the row's External ID, whether its document syncs on the Connection, or both;
	what is not given stays. The External ID can be emptied only on a document that does not
	sync, and a document without one cannot be set to sync: it would be created in the API
	again."""
	frappe.only_for("System Manager")
	row = writable_link(name)
	values: dict[str, Any] = {}
	if dont_sync is not None:
		values["dont_sync"] = 1 if cint(dont_sync) else 0
	if external_id is not None:
		external_id = external_id.strip()
		if external_id:
			check_external_id(row.sync_connection, row.parenttype, external_id, row.name)
		values["external_id"] = external_id or None
	if not values:
		return as_link(row)
	# whichever of the two is changed: turning the sync on for a link without one as much
	# as emptying it on a document that syncs
	if not values.get("dont_sync", row.dont_sync) and not values.get("external_id", row.external_id):
		frappe.throw(_("An External ID is needed while the document syncs"))
	return write_link(row, values)


@frappe.whitelist(methods=["POST"])
def forget_link(name: str) -> dict[str, Any]:
	"""Forget what was last synced of the document, here and in the API: the next sync takes
	it as changed on both sides, and syncs it again. The link itself stays."""
	frappe.only_for("System Manager")
	row = writable_link(name)
	return write_link(row, {"last_synced_modified": None, "external_modified": None})


@frappe.whitelist(methods=["POST"])
def delete_link(name: str) -> dict[str, bool]:
	"""Remove the link: the document stays, and so does what it is in the API. The next sync
	knows neither as the other, so it may create one of them again."""
	frappe.only_for("System Manager")
	row = writable_link(name)
	frappe.db.delete(SYNC_ID, {"name": row.name})
	frappe.clear_document_cache(row.parenttype, row.parent)
	return {"deleted": True}
