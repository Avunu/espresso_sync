# Copyright (c) 2023, Avunu LLC and contributors
# For license information, please see license.txt

import frappe
import re

from frappe.model.document import Document

class EspressoSyncConnectionShot(Document):
	def get_crud_url(self, crud_action, external_id=None):
		# get the connection
		connection = frappe.get_doc('Espresso Sync Connection', self.parent)

		# get the url domain and url base
		api_domain = connection.api_domain
		api_base = connection.api_base
		api_endpoint = self.uri
		url_scheme = "https://"

		if self.override_url:
			overridden_url = self.url
		if self.override_url_scheme:
			url_scheme = self.url_scheme
		if self.override_api_domain:
			api_domain = self.api_domain
		if self.override_api_base:
			api_base = self.api_base

		url = None
		match crud_action:
			case 'create':
				url = get_create_url(url_scheme, api_domain, api_base, api_endpoint)
			case 'read':
				url = get_read_url(url_scheme, api_domain, api_base, api_endpoint)
			case 'update':
				url = get_update_url(url_scheme, api_domain, api_base, api_endpoint, external_id)
			case 'delete':
				url = get_delete_url(url_scheme, api_domain, api_base, api_endpoint)
		
		# evaluate for dyno params and build all permutations into a list
		urls = permutation_builder(url, self, connection)

		# debug
		frappe.publish_realtime('console.log', 'urls:', user=frappe.session.user)
		frappe.publish_realtime('console.log', urls, user=frappe.session.user)
		# end debug

		return urls

def get_create_url(url_scheme, api_domain, api_base, api_endpoint):

	return url_builder(url_scheme, api_domain, api_base, api_endpoint)

def get_read_url(url_scheme, api_domain, api_base, api_endpoint):
	
	return url_builder(url_scheme, api_domain, api_base, api_endpoint)

def get_update_url(url_scheme, api_domain, api_base, api_endpoint, external_id):
	base_url = url_builder(url_scheme, api_domain, api_base, api_endpoint)
	# add the id to the url
	if external_id:
		base_url = f"{base_url}/{external_id}"
	return base_url

def get_delete_url(url_scheme, api_domain, api_base, api_endpoint):
	
	return url_builder(url_scheme, api_domain, api_base, api_endpoint)

def url_builder(url_scheme, api_domain, api_base, api_endpoint):
	# build the url
	url = f"{url_scheme}{api_domain}{api_base}/{api_endpoint}"
	# return the url
	return url

# This function builds a list of all possible permutations of a url string based on dynamic parameters

def permutation_builder(url, shot, connection):
	half_baked_urls = [url]  # Start with the original URL
	finished_urls = []
	while half_baked_urls:
		url = half_baked_urls.pop()  # Take the last URL from the list

		# debug
		frappe.publish_realtime('console.log', 'url:', user=frappe.session.user)
		frappe.publish_realtime('console.log', url, user=frappe.session.user)
		# end debug

		# Find the first dynamic parameter in the URL string
		first_dynamic_parameter = re.search(r'{(.*?)}', url)

		if first_dynamic_parameter:
			# Get everything between the curly braces
			dynamic_parameter = first_dynamic_parameter.group(1)

			# debug
			frappe.publish_realtime('console.log', 'dynamic_parameter:', user=frappe.session.user)
			frappe.publish_realtime('console.log', dynamic_parameter, user=frappe.session.user)
			# end debug

			if dynamic_parameter.startswith('doc:'):
				# Split the dynamic parameter on the colon
				dynamic_parameter_parts = dynamic_parameter.split(':')
				# Get the doc name
				doc_name = dynamic_parameter_parts[1]
				# Get the doc field
				doc_field = dynamic_parameter_parts[2]
				try:
					# Get the doc value
					doc_value = frappe.db.get_value(doc_name, shot.name, doc_field)
					# Replace the dynamic parameter with the value
					new_url = url.replace(first_dynamic_parameter.group(0), doc_value)
					# Add the new URL to the half_baked_urls list
					half_baked_urls.append(new_url)
				except Exception as e:
					# frappe.show_alert(f"Error getting value for {doc_name} {doc_field}: {e}", alert_type='danger')
					frappe.publish_realtime('show_alert', {'message': f"Error getting value for {doc_name} {doc_field}: {e}", 'indicator': 'orange'}, user=frappe.session.user)
					frappe.log_error(f"Error getting value for {doc_name} {doc_field}: {e}")
					continue

			elif dynamic_parameter.startswith('id:'):
				# Split the dynamic parameter on the colon
				dynamic_parameter_parts = dynamic_parameter.split(':')
				# Get the doc name
				doc_name = dynamic_parameter_parts[1]
				# Get a list of all instances of the doc
				doc_list = frappe.get_all(doc_name)

				# debug
				frappe.publish_realtime('console.log', 'doc_list:', user=frappe.session.user)
				frappe.publish_realtime('console.log', doc_list, user=frappe.session.user)
				# end debug

				# Loop through the list of docs
				for doc in doc_list:
					try:

						# get the doc
						doc = frappe.get_doc(doc_name, doc.name)

						# debug
						frappe.publish_realtime('console.log', 'doc:', user=frappe.session.user)
						frappe.publish_realtime('console.log', doc, user=frappe.session.user)
						# end debug

						# Get the external id of the doc for this connection
						# looks something like this: frappe.db.get_value(doctype="Espresso Sync ID", filters={'sync_connection': sync_connection.name, 'parent': doc[value.split(":")[1:][0]]}, fieldname="external_id")
						external_id = frappe.db.get_value(doctype="Espresso Sync ID", filters={'sync_connection': connection.name, 'parent': doc}, fieldname="external_id")

						# debug
						frappe.publish_realtime('console.log', 'external_id:', user=frappe.session.user)
						frappe.publish_realtime('console.log', external_id, user=frappe.session.user)
						# end debug

						# If there is an external id, replace the dynamic parameter with the external id
						if external_id:
							new_url = url.replace(first_dynamic_parameter.group(0), external_id)
							# Add the new URL to the half_baked_urls list
							half_baked_urls.append(new_url)
					except Exception as e:
						# frappe.show_alert(f"Error getting external id for {doc_name}: {e}", alert_type='danger')
						frappe.publish_realtime('show_alert', {'message': f"Error getting external id for {doc_name}: {e}", 'indicator': 'orange'}, user=frappe.session.user)
						frappe.log_error(f"Error getting external id for {doc_name}: {e}")
						continue

			else:
				# Handle the dyno param as jinja
				try:
					# Replace the dynamic parameter with the value
					new_url = url.replace(first_dynamic_parameter.group(0), frappe.render_template(dynamic_parameter, shot.as_dict()))
					# Add the new URL to the half_baked_urls list
					half_baked_urls.append(new_url)
				except Exception as e:
					# frappe.show_alert(f"Error rendering template: {e}", alert_type='danger')
					frappe.publish_realtime('show_alert', {'message': f"Error rendering template: {e}", 'indicator': 'orange'}, user=frappe.session.user)
					frappe.log_error(f"Error rendering template: {e}")

		# If there are no dynamic parameters, add the URL to the finished_urls list
		else:
			finished_urls.append(url)
	return finished_urls