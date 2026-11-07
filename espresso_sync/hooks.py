# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

app_name = "espresso_sync"
app_title = "Espresso Sync"
app_publisher = "Avunu LLC"
app_description = "Two-way sync between Frappe documents and external REST APIs"
app_email = "mail@avu.nu"
app_license = "MIT"

add_to_apps_screen = [
	{
		"name": "espresso_sync",
		"logo": "/assets/espresso_sync/images/espresso_sync-logo.svg",
		"title": "Espresso Sync",
		"route": "/desk",
		"has_permission": "espresso_sync.apps_screen.not_listed",
	}
]

export_python_type_annotations = True
