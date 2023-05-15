# Copyright (c) 2023, Avunu LLC and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document

class EspressoSyncConnectionShot(Document):
	def create_url(self):
		pass

	def url_builder(self):
		# debug
		frappe.publish_realtime('console.log', 'url builder', user=frappe.session.user)
		frappe.publish_realtime('console.log', self, user=frappe.session.user)
		pass

	def update_url(self):
		pass

	def mapping_template(self):
		pass