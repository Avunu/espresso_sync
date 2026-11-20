# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""The portal's linked documents: listing the Espresso Sync ID rows, and changing them
without touching the document they are rows of."""

import inspect
from typing import Any, cast
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from espresso_sync import sync
from espresso_sync.api import links as api

CONNECTION = "Espresso Sync Connection"
SYNC_ID = "Espresso Sync ID"
SHOP = "ES Links API Test Shop"
OTHER = "ES Links API Test Other"
MANAGER = "es-links-manager@example.com"
OUTSIDER = "es-links-outsider@example.com"
READS = ("list_links",)
WRITES = ("add_link", "update_link", "forget_link", "delete_link")


def make_user(email: str, roles: list[str]) -> str:
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"roles": [{"role": role} for role in roles],
			}
		).insert(ignore_permissions=True)
	return email


def make_connection(name: str) -> str:
	if not frappe.db.exists(CONNECTION, name):
		frappe.get_doc(
			{
				"doctype": CONNECTION,
				"connection_name": name,
				"auth_type": "Header-based",
				"api_key": "X-Api-Key",
				"api_secret": "links-api-secret",
				"server_url": "https://api.example.invalid/v1",
				"sync_frequency": "Manual",
			}
		).insert(ignore_permissions=True)
	return name


class TestLinksEndpoints(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		make_user(MANAGER, ["System Manager"])
		make_user(OUTSIDER, ["Website Manager"])
		make_connection(SHOP)
		make_connection(OTHER)
		sync.ensure_sync_fields("ToDo")

	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.db.delete(SYNC_ID, {"sync_connection": ("in", (SHOP, OTHER))})
		frappe.set_user(MANAGER)

	def todo(self, label: str = "") -> str:
		doc = frappe.get_doc({"doctype": "ToDo", "description": f"es {self._testMethodName} {label}"})
		return str(doc.insert().name)

	def linked(self, external_id: str | None, connection: str = SHOP, **values) -> dict[str, Any]:
		"""A new ToDo with a Sync ID row, made the way a sync makes it: through the document."""
		doc = cast("Any", frappe.get_doc("ToDo", self.todo(external_id or "")))
		row = doc.append(
			"espresso_sync_ids", {"sync_connection": connection, "external_id": external_id, **values}
		)
		doc.save()
		return {"name": row.name, "parent": doc.name}

	def modified(self, todo: str) -> Any:
		return frappe.db.get_value("ToDo", todo, "modified")

	def row(self, name: str) -> Any:
		return frappe.db.get_value(
			SYNC_ID,
			name,
			["external_id", "dont_sync", "last_synced_modified", "external_modified", "modified", "idx"],
			as_dict=True,
		)

	def test_only_these_are_whitelisted_and_writes_are_post_only(self):
		whitelisted = {
			name for name, fn in inspect.getmembers(api, inspect.isfunction) if fn in frappe.whitelisted
		}
		self.assertEqual(whitelisted, {*READS, *WRITES})
		for name in WRITES:
			self.assertEqual(
				frappe.allowed_http_methods_for_whitelisted_func[getattr(api, name)], ["POST"], name
			)

	def test_only_a_system_manager_may_call_any_of_them(self):
		link = self.linked("ext-1")
		todo = self.todo("unlinked")
		frappe.set_user(OUTSIDER)
		calls = {
			"list_links": lambda: api.list_links(SHOP),
			"add_link": lambda: api.add_link(SHOP, "ToDo", todo, "ext-2"),
			"update_link": lambda: api.update_link(link["name"], external_id="ext-3"),
			"forget_link": lambda: api.forget_link(link["name"]),
			"delete_link": lambda: api.delete_link(link["name"]),
		}
		self.assertEqual(set(calls), {*READS, *WRITES})
		for name, call in calls.items():
			with self.subTest(endpoint=name), self.assertRaises(frappe.PermissionError):
				call()
		self.assertEqual(self.row(link["name"]).external_id, "ext-1")
		self.assertEqual(frappe.db.count(SYNC_ID, {"sync_connection": SHOP}), 1)

	def test_list_links_pages_through_the_connections_rows(self):
		links = [self.linked(f"page-{n}") for n in range(5)]
		self.linked("elsewhere", connection=OTHER)

		first = api.list_links(SHOP, limit=2)
		second = api.list_links(SHOP, start=2, limit=2)
		last = api.list_links(SHOP, start=4, limit=2)

		self.assertEqual((first["total"], second["total"], last["total"]), (5, 5, 5))
		self.assertEqual([len(page["rows"]) for page in (first, second, last)], [2, 2, 1])
		names = [row["name"] for page in (first, second, last) for row in page["rows"]]
		self.assertEqual(sorted(names), sorted(link["name"] for link in links))
		self.assertEqual(len(set(names)), 5)
		self.assertEqual(
			set(first["rows"][0]),
			{
				"name",
				"parenttype",
				"parent",
				"external_id",
				"last_synced_modified",
				"external_modified",
				"dont_sync",
			},
		)
		self.assertEqual(first["doctypes"], ["ToDo"])
		# a page is never more than a hundred, and never less than one
		self.assertEqual(len(api.list_links(SHOP, limit=10**6)["rows"]), 5)
		self.assertEqual(len(api.list_links(SHOP, start=-5, limit=0)["rows"]), 1)

	def test_list_links_filters_by_doctype_search_and_not_syncing(self):
		first = self.linked("acme/website")
		second = self.linked("acme/100%_done")
		paused = self.linked(None, dont_sync=1)

		def found(**kwargs) -> list[str]:
			return [row["name"] for row in api.list_links(SHOP, **kwargs)["rows"]]

		self.assertCountEqual(found(search="acme"), [first["name"], second["name"]])
		self.assertEqual(found(search=" website "), [first["name"]])
		# by the document's name as well as its External ID
		self.assertEqual(found(search=second["parent"]), [second["name"]])
		# the search's own wildcards are literal
		self.assertEqual(found(search="100%_done"), [second["name"]])
		self.assertEqual(found(search="%"), [second["name"]])
		self.assertEqual(found(search="a_me"), [])
		self.assertEqual(found(not_syncing=1), [paused["name"]])
		self.assertEqual(len(found(not_syncing=0, search="  ")), 3)
		self.assertEqual(len(found(doctype="ToDo")), 3)

		other = api.list_links(SHOP, doctype="Contact")
		self.assertEqual((other["rows"], other["total"]), ([], 0))
		# what there is to filter by does not narrow with the filter
		self.assertEqual(other["doctypes"], ["ToDo"])
		self.assertEqual(api.list_links(SHOP, search="acme")["total"], 2)
		self.assertEqual(api.list_links(OTHER), {"rows": [], "total": 0, "doctypes": []})

	def test_list_links_of_a_missing_connection_is_refused(self):
		with self.assertRaises(frappe.DoesNotExistError):
			api.list_links("ES Links API No Such Shop")

	def test_add_link_inserts_the_row_and_leaves_the_document(self):
		existing = self.linked("other-1", connection=OTHER)
		todo = existing["parent"]
		modified = self.modified(todo)

		link = api.add_link(SHOP, "ToDo", todo, "  ext-9  ")

		self.assertEqual(
			link,
			{
				"name": link["name"],
				"parenttype": "ToDo",
				"parent": todo,
				"external_id": "ext-9",
				"last_synced_modified": None,
				"external_modified": None,
				"dont_sync": 0,
			},
		)
		self.assertEqual(self.modified(todo), modified)
		# a row of the document's Sync tab, after the one it had
		doc = cast("Any", frappe.get_doc("ToDo", todo))
		self.assertEqual(
			[(row.sync_connection, row.external_id, row.idx) for row in doc.espresso_sync_ids],
			[(OTHER, "other-1", 1), (SHOP, "ext-9", 2)],
		)
		# and the sync finds the document by it
		self.assertEqual(sync.imported_row(SHOP, "ToDo", "ext-9").parent, todo)

	def test_add_link_refuses_what_cannot_be_linked(self):
		link = self.linked("ext-1")
		todo = self.todo("unlinked")
		refused = {
			"a second link of the document": (SHOP, "ToDo", link["parent"], "ext-2"),
			"an External ID another document has": (SHOP, "ToDo", todo, "ext-1"),
			"no External ID": (SHOP, "ToDo", todo, "  "),
			"a DocType without the Sync tab": (SHOP, "Role", "System Manager", "ext-2"),
			"no such DocType": (SHOP, "ES Links API No Such DocType", "x", "ext-2"),
		}
		for reason, args in refused.items():
			with self.subTest(reason=reason), self.assertRaises(frappe.ValidationError):
				api.add_link(*args)
		with self.assertRaises(frappe.DoesNotExistError):
			api.add_link(SHOP, "ToDo", "es-links-no-such-todo", "ext-2")
		with self.assertRaises(frappe.DoesNotExistError):
			api.add_link("ES Links API No Such Shop", "ToDo", todo, "ext-2")
		self.assertEqual(frappe.db.count(SYNC_ID, {"sync_connection": SHOP}), 1)
		# the same External ID is another thing on another Connection
		self.assertEqual(api.add_link(OTHER, "ToDo", todo, "ext-1")["external_id"], "ext-1")

	def test_add_link_needs_write_on_the_document(self):
		todo = self.todo()
		# refused as what the portal shows, not as the 403 it takes for a session that ended
		with (
			patch.object(api.frappe, "has_permission", return_value=False) as checked,
			self.assertRaises(frappe.ValidationError) as refused,
		):
			api.add_link(SHOP, "ToDo", todo, "ext-1")
		self.assertNotIsInstance(refused.exception, frappe.PermissionError)
		checked.assert_called_once_with("ToDo", "write", todo)
		self.assertEqual(frappe.db.count(SYNC_ID, {"sync_connection": SHOP}), 0)

	def test_update_link_changes_the_row_and_leaves_the_document(self):
		link = self.linked("ext-1")
		modified = self.modified(link["parent"])
		row_modified = self.row(link["name"]).modified

		updated = api.update_link(link["name"], external_id=" ext-2 ")
		self.assertEqual((updated["external_id"], updated["dont_sync"]), ("ext-2", 0))
		updated = api.update_link(link["name"], dont_sync=1)
		self.assertEqual((updated["external_id"], updated["dont_sync"]), ("ext-2", 1))
		updated = api.update_link(link["name"], external_id="ext-3", dont_sync=0)
		self.assertEqual((updated["external_id"], updated["dont_sync"]), ("ext-3", 0))
		# nothing given: nothing changed
		self.assertEqual(api.update_link(link["name"]), updated)

		row = self.row(link["name"])
		self.assertEqual((row.external_id, row.dont_sync, row.modified), ("ext-3", 0, row_modified))
		self.assertEqual(self.modified(link["parent"]), modified)

	def test_update_link_refuses_an_empty_external_id_while_the_document_syncs(self):
		link = self.linked("ext-1")
		for kwargs in ({"external_id": ""}, {"external_id": "  "}, {"external_id": "", "dont_sync": 0}):
			with self.subTest(kwargs=kwargs), self.assertRaises(frappe.ValidationError):
				api.update_link(link["name"], **kwargs)
		self.assertEqual(self.row(link["name"]).external_id, "ext-1")

		# emptied together with turning its sync off, or once it is off
		updated = api.update_link(link["name"], external_id="", dont_sync=1)
		self.assertEqual((updated["external_id"], updated["dont_sync"]), (None, 1))
		api.update_link(link["name"], external_id="ext-1")
		self.assertIsNone(api.update_link(link["name"], external_id="")["external_id"])
		# and its sync is not turned on again without one: it would be created in the API again
		for kwargs in ({"dont_sync": 0}, {"dont_sync": 0, "external_id": " "}):
			with self.subTest(kwargs=kwargs), self.assertRaises(frappe.ValidationError):
				api.update_link(link["name"], **kwargs)
		self.assertEqual(self.row(link["name"]).dont_sync, 1)
		updated = api.update_link(link["name"], dont_sync=0, external_id="ext-1")
		self.assertEqual((updated["external_id"], updated["dont_sync"]), ("ext-1", 0))

	def test_update_link_refuses_an_external_id_another_document_has(self):
		first = self.linked("ext-1")
		second = self.linked("ext-2")
		with self.assertRaises(frappe.ValidationError):
			api.update_link(second["name"], external_id="ext-1")
		self.assertEqual(self.row(second["name"]).external_id, "ext-2")
		# its own is not another's
		self.assertEqual(api.update_link(first["name"], external_id="ext-1")["external_id"], "ext-1")

	def test_forget_link_clears_what_was_synced_and_leaves_the_document(self):
		link = self.linked(
			"ext-1", last_synced_modified="2026-01-15 09:00:00", external_modified="2026-01-15 08:00:00"
		)
		modified = self.modified(link["parent"])
		self.assertEqual(api.list_links(SHOP)["rows"][0]["last_synced_modified"][:19], "2026-01-15 09:00:00")

		forgotten = api.forget_link(link["name"])

		self.assertEqual(
			(forgotten["external_id"], forgotten["last_synced_modified"], forgotten["external_modified"]),
			("ext-1", None, None),
		)
		row = self.row(link["name"])
		self.assertEqual((row.last_synced_modified, row.external_modified), (None, None))
		self.assertEqual(self.modified(link["parent"]), modified)

	def test_delete_link_removes_the_row_and_leaves_the_document(self):
		link = self.linked("ext-1")
		modified = self.modified(link["parent"])

		self.assertEqual(api.delete_link(link["name"]), {"deleted": True})

		self.assertFalse(frappe.db.exists(SYNC_ID, link["name"]))
		self.assertEqual(self.modified(link["parent"]), modified)
		self.assertEqual(cast("Any", frappe.get_doc("ToDo", link["parent"])).espresso_sync_ids, [])

	def test_a_row_that_is_not_there_is_refused(self):
		for call in (api.update_link, api.forget_link, api.delete_link):
			with self.subTest(endpoint=call.__name__), self.assertRaises(frappe.DoesNotExistError):
				call("es-links-no-such-row")

	def test_a_row_of_a_connection_without_write_is_refused(self):
		link = self.linked("ext-1", connection=OTHER, external_modified="2026-01-15 08:00:00")

		def only_the_shop(connection: str, ptype: str) -> None:
			if connection != SHOP:
				raise frappe.PermissionError

		calls = {
			"update_link": lambda: api.update_link(link["name"], external_id="ext-2"),
			"forget_link": lambda: api.forget_link(link["name"]),
			"delete_link": lambda: api.delete_link(link["name"]),
			"add_link": lambda: api.add_link(OTHER, "ToDo", self.todo("unlinked"), "ext-3"),
		}
		self.assertEqual(set(calls), set(WRITES))
		with patch.object(api, "check_connection", side_effect=only_the_shop) as checked:
			for name, call in calls.items():
				with self.subTest(endpoint=name), self.assertRaises(frappe.PermissionError):
					call()
		self.assertEqual([args.args for args in checked.call_args_list], [(OTHER, "write")] * 4)
		row = self.row(link["name"])
		self.assertEqual(row.external_id, "ext-1")
		self.assertIsNotNone(row.external_modified)
		self.assertEqual(frappe.db.count(SYNC_ID, {"sync_connection": OTHER}), 1)

	def test_a_row_of_a_document_without_write_is_refused(self):
		link = self.linked("ext-1", external_modified="2026-01-15 08:00:00")
		calls = {
			"update_link": lambda: api.update_link(link["name"], dont_sync=1),
			"forget_link": lambda: api.forget_link(link["name"]),
			"delete_link": lambda: api.delete_link(link["name"]),
		}
		for name, call in calls.items():
			with (
				self.subTest(endpoint=name),
				patch.object(api.frappe, "has_permission", return_value=False) as checked,
				self.assertRaises(frappe.ValidationError) as refused,
			):
				call()
			self.assertNotIsInstance(refused.exception, frappe.PermissionError)
			checked.assert_called_once_with("ToDo", "write", link["parent"])
		row = self.row(link["name"])
		self.assertEqual((row.external_id, row.dont_sync), ("ext-1", 0))
		self.assertIsNotNone(row.external_modified)
