# Copyright (c) 2023, Avunu LLC and contributors
# For license information, please see license.txt

import json

import frappe


def process_sync_connections():
	sync_connection_names = frappe.get_list(
		"Espresso Sync Connection", filters={"pull_shot": 1}, pluck="name"
	)
	for sync_connection_name in sync_connection_names:
		sync_connection = frappe.get_doc("Espresso Sync Connection", sync_connection_name)
		sync_connection.sync()


@frappe.whitelist()
def process_sync_connection_form_action(doc: str):
	from espresso_sync.espresso_sync.doctype.espresso_sync_connection.espresso_sync_connection import (
		require_sync_manager,
	)

	require_sync_manager()
	doc_name = frappe._dict(json.loads(doc)).name
	sync_connection = frappe.get_doc("Espresso Sync Connection", doc_name)
	require_sync_manager(sync_connection, "write")
	sync_connection.sync()
	return sync_connection


# function to add a log of the sync to the espresso_sync_log table on the espresso_sync_history doctype
# the table fields are timestamp, sync_connection, sync_shot, sync_doctype, sync_object, sync_document, traceback, sync_direction, and sync_status
def add_sync_log(
	espresso_sync_log=None,
	sync_connection=None,
	sync_shot=None,
	sync_doctype=None,
	sync_object=None,
	sync_document=None,
	traceback=None,
	call_string=None,
	sync_direction=None,
	sync_status=None,
):
	# create a new espresso_sync_log document
	if not espresso_sync_log:
		espresso_sync_log = frappe.new_doc("Espresso Sync Log")
	# set the fields
	if sync_connection:
		espresso_sync_log.sync_connection = sync_connection
	if sync_shot:
		espresso_sync_log.sync_shot = sync_shot
	if sync_doctype:
		espresso_sync_log.sync_doctype = sync_doctype
	if sync_object:
		espresso_sync_log.sync_object = sync_object
	if sync_document:
		espresso_sync_log.sync_document = sync_document
	if traceback:
		espresso_sync_log.traceback = traceback
	if call_string:
		espresso_sync_log.call_string = call_string
	if sync_direction:
		espresso_sync_log.sync_direction = sync_direction
	if sync_status:
		espresso_sync_log.sync_status = sync_status
	# save the document
	espresso_sync_log.save()
	frappe.db.commit()

	return espresso_sync_log
