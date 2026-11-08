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
		"route": "/espresso_sync",
		"has_permission": "espresso_sync.apps_screen.check_app_permission",
	}
]

export_python_type_annotations = True

# Scheduled syncs: each event enqueues a sync of the enabled Connections whose Sync Frequency
# it runs ("Every Minute" is every scheduler tick; "Cron" reads each Connection's Cron Rule).
scheduler_events = {
	"all": ["espresso_sync.scheduler.sync_all"],
	"hourly": ["espresso_sync.scheduler.sync_hourly"],
	"daily": ["espresso_sync.scheduler.sync_daily"],
	"weekly": ["espresso_sync.scheduler.sync_weekly"],
	"monthly": ["espresso_sync.scheduler.sync_monthly"],
	"cron": {"* * * * *": ["espresso_sync.scheduler.sync_cron"]},
}

# Log Settings deletes Pull Log entries older than this many days (changeable there)
default_log_clearing_doctypes = {"Espresso Sync Pull Log": 30}
