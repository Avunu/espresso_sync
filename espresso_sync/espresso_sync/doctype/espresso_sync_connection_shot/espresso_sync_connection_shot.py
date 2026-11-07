# Copyright (c) 2023, Avunu LLC and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class EspressoSyncConnectionShot(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		api_base: DF.Data | None
		api_domain: DF.Data | None
		delete_uri: DF.Data | None
		do_export: DF.Check
		do_import: DF.Check
		dt: DF.Link
		export_existing: DF.Check
		export_request_type: DF.Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
		filter_documents: DF.Check
		filters: DF.JSON | None
		get_uri: DF.Data | None
		id_field_map: DF.Data | None
		import_request_type: DF.Literal["GET", "POST", "PUT", "PATCH"]
		last_export: DF.Datetime | None
		last_import: DF.Datetime | None
		modified_date_field_map: DF.Data | None
		modified_date_format: DF.Data | None
		object_map_export: DF.JSON | None
		object_map_import: DF.JSON | None
		objects_key: DF.Data | None
		override_api_base: DF.Check
		override_api_domain: DF.Check
		override_export_request_type: DF.Check
		override_import_request: DF.Check
		override_uris: DF.Check
		override_url_scheme: DF.Check
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		post_uri: DF.Data | None
		put_uri: DF.Data | None
		reference_count: DF.Int
		reference_doc: DF.Code | None
		reference_docs: DF.JSON | None
		reference_index: DF.Int
		request_payload: DF.JSON | None
		sample_count: DF.Int
		sample_index: DF.Int
		sample_object: DF.Code | None
		sample_objects: DF.JSON | None
		uri: DF.Data
		url_scheme: DF.Data | None
	# end: auto-generated types

	def get_crud_uri(self, url, crud_action, external_id=None):
		# scrub double quotes from url
		url = url.replace('"', "")
		match crud_action:
			case "create":
				return get_create_uri(url)
			case "read":
				return get_read_uri(self, url)
			case "update":
				return get_update_uri(url, external_id)
			case "delete":
				return get_delete_uri(url)

	def get_api_url(self):
		# get the connection
		from espresso_sync.espresso_sync.doctype.espresso_sync_connection.espresso_sync_connection import (
			get_connection,
		)

		connection = get_connection(self.parent)

		# get the url pieces
		url_scheme = "https://"
		api_domain = connection.api_domain
		api_base = connection.api_base
		api_endpoint = self.uri

		if self.override_url_scheme:
			url_scheme = self.url_scheme
		if self.override_api_domain:
			api_domain = self.api_domain
		if self.override_api_base:
			api_base = self.api_base

		return f"{url_scheme}{api_domain}{api_base}/{api_endpoint}"


def get_create_uri(url):
	return url


def get_read_uri(self, url):
	if self.override_uris:
		return url.replace(self.uri, self.get_uri)
	return url


def get_update_uri(url, external_id):
	if external_id:
		url = f"{url}/{external_id}"
	return url


def get_delete_uri(url):
	return url
