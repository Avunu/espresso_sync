# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""A Transform run on its sample, with nothing kept.

An import maps each sample item and inserts the document, with every hook Frappe runs on
an insert, then rolls it back to a savepoint: the rows it wrote go, and so do the
callbacks it queued for the commit and the rollback. While it runs, a commit raises (it
would keep what the savepoint is there to undo), and jobs (however a hook enqueues one,
it reaches RQ through Queue.enqueue_call), realtime events and emails are not sent. What
a hook does outside the database is not undone: one that changes the database schema
still commits (MariaDB commits DDL), and one that makes an HTTP request makes it.

An export maps each sample document and checks it against the request body: nothing is
sent.
"""

import copy
from collections import deque
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import frappe
from frappe import _
from rq import Queue

from espresso_sync.transform import validate
from espresso_sync.transform.compile import compile_rules

SAVEPOINT = "espresso_sync_dry_run"
CALLBACKS = ("before_commit", "after_commit", "before_rollback", "after_rollback")


class CommitRefused(frappe.ValidationError):
	pass


def refuse_commit(*args, **kwargs):
	raise CommitRefused(_("A dry run cannot commit"))


def skip(*args, **kwargs):
	return None


@contextmanager
def nothing_kept() -> Generator[None]:
	"""Run the block, then undo what it wrote to the database and queued for the commit.
	Inside it, a commit raises CommitRefused, and jobs, realtime events and emails are not
	sent."""
	db = frappe.local.db
	queued = {name: list(getattr(db, name)._functions) for name in CALLBACKS}
	mute_emails = frappe.flags.mute_emails
	frappe.flags.mute_emails = True
	db.savepoint(SAVEPOINT)
	try:
		with (
			patch.object(db, "commit", refuse_commit),
			patch.object(Queue, "enqueue_call", skip),
			patch.object(frappe, "publish_realtime", skip),
		):
			yield
	finally:
		db.rollback(save_point=SAVEPOINT)
		for name, functions in queued.items():
			getattr(db, name)._functions = deque(functions)
		frappe.flags.mute_emails = mute_emails


def insert(doctype: str, output: dict[str, Any], index: int) -> tuple[str | None, list[dict[str, Any]]]:
	"""(the name the document got, or None, and what went wrong) when inserted as the
	session user, nothing kept."""
	with nothing_kept(), validate.without_messages():
		try:
			# get_doc fills in the rows it is given: the output stays as mapped
			doc = frappe.get_doc(copy.deepcopy({**output, "doctype": doctype}))
			doc.insert()
		except Exception as e:
			return None, [
				validate.diagnostic(
					"", "", "error", f"dry-run.{type(e).__name__}", validate.error_message(e), index
				)
			]
		return doc.name, []


def dry_run(transform) -> list[dict[str, Any]]:
	"""For each sample item: {item, output (the mapped object), name (an import's document,
	as it was named), diagnostics}."""
	sides = validate.Sides(transform)
	rules = transform.get_rules()
	compiled = compile_rules(rules)
	kinds = validate.rule_kinds(rules)
	results = []
	for index, item in enumerate(transform.get_sample()[: validate.MAX_SAMPLE_ITEMS]):
		output, diagnostics = validate.map_item(sides, compiled, kinds, item, index)
		name = None
		if sides.importing and isinstance(output, dict):
			name, failures = insert(transform.document_type, output, index)
			diagnostics.extend(failures)
		results.append({"item": index, "output": output, "name": name, "diagnostics": diagnostics})
	return results
