# Copyright (c) 2023, Avunu LLC and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class EspressoSyncConnectionShot(Document):
	def get_crud_url(self, crud_action, external_id=None):
		# get the parent
		parent = frappe.get_doc('Espresso Sync Connection', self.parent)

		# get the url domain and url base
		api_domain = parent.api_domain
		api_base = parent.api_base
		api_endpoint = self.uri

		if self.override_api_base:
			api_base = self.api_base

		match crud_action:
			case 'create':
				return get_create_url(api_domain, api_base, api_endpoint)
			case 'read':
				return get_read_url(api_domain, api_base, api_endpoint)
			case 'update':
				return get_update_url(api_domain, api_base, api_endpoint, external_id)
			case 'delete':
				return get_delete_url(api_domain, api_base, api_endpoint)

def get_create_url(api_domain, api_base, api_endpoint):

	return url_builder(api_domain, api_base, api_endpoint)

def get_read_url(api_domain, api_base, api_endpoint):
	
	return url_builder(api_domain, api_base, api_endpoint)

def get_update_url(api_domain, api_base, api_endpoint, external_id):
	base_url = url_builder(api_domain, api_base, api_endpoint)
	# add the id to the url
	if external_id:
		base_url = f"{base_url}/{external_id}"
	return base_url

def get_delete_url(api_domain, api_base, api_endpoint):
	
	return url_builder(api_domain, api_base, api_endpoint)

def url_builder(api_domain, api_base, api_endpoint):
	# build the url
	url = f"https://{api_domain}{api_base}/{api_endpoint}"
	# return the url
	return url