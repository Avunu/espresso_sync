# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""Remove the Espresso Sync Batch DocType, which nothing ever wrote to, and its table."""

import frappe

DOCTYPE = "Espresso Sync Batch"


def execute():
	for doctype, field in (
		("Custom Field", "dt"),
		("Property Setter", "doc_type"),
		("Custom DocPerm", "parent"),
	):
		frappe.db.delete(doctype, {field: DOCTYPE})
	frappe.delete_doc("DocType", DOCTYPE, force=True, ignore_missing=True)
	frappe.db.sql_ddl("DROP TABLE IF EXISTS `tabEspresso Sync Batch`")
