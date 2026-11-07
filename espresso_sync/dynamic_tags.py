# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

import frappe
from jsonpath_ng import parse


def doc_tag(params, object, sync_connection, doc):
	"""
	This function handles "doc" tags, which are used to fetch values from "Single" doctypes. This is useful for pulling parameters from global settings.
	Example: "{doc:Selling Settings:default_price_list}" - fetches the default price list from the Selling Settings doctype.
	"""
	try:
		return frappe.db.get_single_value(params.split(":")[0], params.split(":")[1])
	except Exception as e:
		frappe.log_error(f"Error handling doc dynamic tag {params}: {e}")
		return None


def id_tag(params, object, sync_connection, doc):
	"""
	This function handles "id" tags, which are used to fetch the external ID of a linked doc.
	params: the name of the field which contains the document to fetch the external ID from
	Example: "{id:project}" - fetches the external ID of the linked doc in the project field.
	"""
	try:
		return frappe.db.get_value(
			doctype="Espresso Sync ID",
			filters={"sync_connection": sync_connection.name, "parent": doc[params]},
			fieldname="external_id",
		)
	except Exception as e:
		frappe.log_error(f"Error handling id dynamic tag {params}: {e}")
		return None


def link_tag(params, object, sync_connection, doc):
	"""
	This function handles "link" tags, which are used to fetch a frappe doc name based on an external ID.
	Example: "{link:Customer:$.clientId}" - fetches the name of the linked Customer doctype using the client ID.
	"""
	try:
		doctype, id = params.split(":")
		jsonpath_expr = parse(id)
		matches = [match.value for match in jsonpath_expr.find(object)]
		if not matches:
			return None
		external_id = matches[0]
		# return the frappe doc whose espresso_sync_id matches the client ID for the sync connection
		return frappe.db.get_value(
			doctype="Espresso Sync ID",
			filters={
				"sync_connection": sync_connection.name,
				"parenttype": doctype,
				"external_id": external_id,
			},
			fieldname="parent",
		)
	except Exception as e:
		frappe.log_error(f"Error handling link dynamic tag {params}: {e}")
		return None


def get_value_tag(params, object, sync_connection, doc):
	"""
	This function handles "get_value" tags, which are used to fetch the value of a field based on given Doctype and filters.
	params: the doctype, fieldname, and filters to use to fetch the value
	Example: "{get_value:Country:name:code=$.billing.country}" - fetches the name of the country based on the billing country code.
	"""
	try:
		# Splitting by ':' to get the individual components
		doctype, fieldname, filters = params.split(":")

		# Extracting filter values using JSONPath
		filter_dict = {}
		for f in filters.split("&"):
			filter_key, jsonpath_expr = f.split("=")

			# Check if the expression starts with '$', which indicates it's a JSONPath expression
			if jsonpath_expr.startswith("$"):
				# Extract value using JSONPath expression
				filter_value = parse(jsonpath_expr).find(object)

				# If the expression finds a match in the object, get the first value
				if filter_value:
					filter_dict[filter_key] = filter_value[0].value
			else:
				filter_dict[filter_key] = jsonpath_expr  # It's a static value

		# Use Frappe's `get_value` function to fetch the desired value from the database
		return frappe.get_value(doctype, filters=filter_dict, fieldname=fieldname)

	except Exception as e:
		frappe.log_error(f"Error handling get_value dynamic tag {params}: {e}")
		return None


def link_value_tag(params, object, sync_connection, doc):
	"""
	This function handles "value" tags, which are used to fetch the value of a field from a linked document.
	params: the name of the field which contains the document to fetch the value from, and the field to fetch the value from
	Example: "{value:customer:email_id}" - fetches the customer's email address from a Sales Order.
	"""
	try:
		linkfield, valuefield = params.split(":")
		docname = doc[linkfield]
		doctype = frappe.get_meta(doc["doctype"]).get_link_doctype(linkfield)
		return frappe.get_value(doctype, docname, valuefield)
	except Exception as e:
		frappe.log_error(f"Error handling value dynamic tag {params}: {e}")
		return None


# def meta_tag(params, object, sync_connection, doc):
#     """
#     This function handles "meta" tags.
#     Example: "{meta:image_id}" - fetches the value of the image_id meta field associated with the Espresso Sync Metadata table for the sync connection and doc.
#     """
#     try:
#         return frappe.db.get_value(
#             doctype="Espresso Sync Metadata",
#             filters={'sync_connection': sync_connection.name,
#                      'parent': doc.name,
#                      'key': params},
#             fieldname='value'
#         )

#     except Exception as e:
#         frappe.log_error(f"Error handling dynamic tag {params}: {e}")
#         return None


def extract_dynamic_tag(tag, object, sync_connection, doc):
	"""
	This function identifies the tag type and calls the respective handler function.
	:param tag: the entire tag string (e.g., "{doc:Selling Settings:default_price_list}")
	:param object: the data object that data will be fetched from
	:param sync_connection: the Espresso Sync Connection
	:param doc: the associated frappe doc as a dictionary (used for exporting)
	"""
	# take the brackets off
	tag = tag[1:-1]
	tag_type = tag.split(":")[0]
	params = ":".join(tag.split(":")[1:])
	handlers = {
		"doc": doc_tag,
		"get_value": get_value_tag,
		"id": id_tag,
		"link_value": link_value_tag,
		"link": link_tag,
		# "docs": docs_tag,
	}
	if tag_type in handlers:
		try:
			return handlers[tag_type](params, object, sync_connection, doc)
		except Exception as e:
			frappe.log_error(f"Error handling dynamic tag {tag}: {e}")
			return None
	else:
		frappe.log_error(f"Unknown dynamic tag type {tag_type}")
		return None


def docs_tag(params, object, sync_connection, doc):
	# Handle the dyno tag as a list of docs
	# Get the doctype from the dynamic tag
	doctype = params.split(":")[1]
	# dynamic_tag_doc_list = frappe.get_all(doctype="Espresso Sync ID", filters={'sync_connection': sync_connection.name, 'parenttype': doctype}, fields=['external_id'])

	# Get the list of doc names from the doctype
	try:
		doc_names = frappe.db.get_list(doctype, pluck="name", limit=10)
		# Get the list of external IDs from the Espresso Sync ID doctype
		return frappe.db.get_list(
			"Espresso Sync ID",
			filters={
				"sync_connection": sync_connection.name,
				"parenttype": doctype,
				"parent": ["in", doc_names],
			},
			fields=["external_id"],
		)
	except Exception as e:
		frappe.log_error(f"Error handling docs dynamic tag {params}: {e}")
		return None
