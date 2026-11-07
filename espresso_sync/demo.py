# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""Demo data for frappe-demo and the screenshots in docs/screenshots/.

One Connection to a made-up shop API with a shot that imports its tasks as ToDos.
Nothing is synced: the demo never reaches the API, and the credential is not real.
"""

import json

import frappe

CONNECTION = "Example Shop"


def setup(ctx):
	"""ctx: today (a datetime.date), seed, company (None without erpnext), erpnext_demo."""
	if frappe.db.exists("Espresso Sync Connection", CONNECTION):
		return
	frappe.get_doc(
		{
			"doctype": "Espresso Sync Connection",
			"connection_name": CONNECTION,
			"auth_type": "Header-based",
			"api_key": "X-Api-Key",
			"api_secret": "demo-key-not-a-real-credential",
			"api_domain": "api.example.com",
			"api_base": "/v1",
			"sync_frequency": "Manual",
			"shots": [
				{
					"dt": "ToDo",
					"uri": "tasks",
					"do_import": 1,
					"id_field_map": "id",
					"object_map_import": json.dumps(
						{"description": "title", "status": "done ? 'Closed' : 'Open'", "date": "due_on"},
						indent=2,
					),
				}
			],
		}
	).insert(ignore_permissions=True)
