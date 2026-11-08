# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""Demo data for frappe-demo and the marketplace screenshots.

One Connection to a made-up shop API, its OpenAPI description, and an Active transform
that imports the shop's tasks as ToDos, run by the Connection's one shot. Nothing is
synced: the demo never reaches the API, and the credential is not real.
"""

import json
from typing import Any

import frappe

CONNECTION = "Example Shop"
SPEC_TITLE = "Shop"
TRANSFORM = "Example Shop Tasks"

SPEC = {
	"openapi": "3.1.0",
	"info": {"title": "Example Shop", "version": "1"},
	"servers": [{"url": "https://api.example.com/v1"}],
	"paths": {
		"/tasks": {
			"get": {
				"operationId": "listTasks",
				"parameters": [{"name": "page", "in": "query", "schema": {"type": "integer"}}],
				"responses": {
					"200": {
						"description": "A page of tasks",
						"content": {
							"application/json": {
								"schema": {
									"type": "object",
									"properties": {
										"data": {
											"type": "array",
											"items": {"$ref": "#/components/schemas/Task"},
										}
									},
								}
							}
						},
					}
				},
			}
		}
	},
	"components": {
		"schemas": {
			"Task": {
				"type": "object",
				"required": ["id", "title"],
				"properties": {
					"id": {"type": "string"},
					"title": {"type": "string"},
					"done": {"type": "boolean"},
					"due_on": {"type": "string", "format": "date"},
					"updated_at": {"type": "string", "format": "date-time"},
				},
			}
		}
	},
}

SAMPLE = [
	{
		"id": "t-101",
		"title": "Restock the espresso beans",
		"done": False,
		"due_on": "2026-01-20",
		"updated_at": "2026-01-15T08:30:00Z",
	},
	{"id": "t-102", "title": "Descale the machine", "done": True, "updated_at": "2026-01-14T17:05:00Z"},
]


def setup(ctx):
	"""ctx: today (a datetime.date), seed, company (None without erpnext), erpnext_demo."""
	if frappe.db.exists("Espresso Sync Connection", CONNECTION):
		return
	connection = frappe.get_doc(
		{
			"doctype": "Espresso Sync Connection",
			"connection_name": CONNECTION,
			"auth_type": "Header-based",
			"api_key": "X-Api-Key",
			"api_secret": "demo-key-not-a-real-credential",
			"server_url": "https://api.example.com/v1",
			"sync_frequency": "Manual",
		}
	).insert(ignore_permissions=True)
	spec = frappe.get_doc(
		{
			"doctype": "Espresso Sync API Spec",
			"title": SPEC_TITLE,
			"connection": connection.name,
			"source_format": "OpenAPI 3.1",
			"spec_json": json.dumps(SPEC),
		}
	).insert(ignore_permissions=True)
	transform: Any = frappe.get_doc(
		{
			"doctype": "Espresso Sync Transform",
			"title": TRANSFORM,
			"direction": "Import",
			"document_type": "ToDo",
			"api_spec": spec.name,
			"method": "GET",
			"path": "/tasks",
			"items_pointer": "/data",
			"query_params": '{"page": 1}',
			"next_request_expr": '$count(body.data) > 0 ? {"page": query.page + 1}',
			"external_id_expr": "id",
			"modified_expr": "updated_at",
			"rules": [
				{"ptr": "/description", "kind": "field", "expr": "title"},
				{"ptr": "/status", "kind": "field", "expr": 'done ? "Closed" : "Open"'},
				{"ptr": "/date", "kind": "field", "expr": "$frappeDate(due_on)"},
			],
			"sample": SAMPLE,
		}
	).insert(ignore_permissions=True)
	transform.activate()
	connection.append("shots", {"dt": "ToDo", "do_import": 1, "import_transform": transform.name})
	connection.save(ignore_permissions=True)
