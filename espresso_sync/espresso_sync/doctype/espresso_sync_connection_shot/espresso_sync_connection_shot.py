# Copyright (c) 2023, Avunu LLC and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class EspressoSyncConnectionShot(Document):
	def get_api_uri(self):
		pass

	def get_crud_uri(self, url, crud_action, external_id=None):

		match crud_action:
			case 'create':
				return get_create_uri(url)
			case 'read':
				return get_read_uri(url)
			case 'update':
				return get_update_uri(url, external_id)
			case 'delete':
				return get_delete_uri(url)

	def get_api_url(self):
		# get the connection
		connection = frappe.get_doc('Espresso Sync Connection', self.parent)

		# get the url pieces
		url_scheme = "https://"
		api_domain = connection.api_domain
		api_base = connection.api_base
		api_endpoint = self.uri

		if self.override_url:
			overridden_url = self.url
		if self.override_url_scheme:
			url_scheme = self.url_scheme
		if self.override_api_domain:
			api_domain = self.api_domain
		if self.override_api_base:
			api_base = self.api_base

		return f"{url_scheme}{api_domain}{api_base}/{api_endpoint}"

def get_create_uri(url):

	return url

def get_read_uri(url):
	
	return url

def get_update_uri(url, external_id):
	if external_id:
		url = f"{url}/{external_id}"
	return url

def get_delete_uri(url):
	
	return url