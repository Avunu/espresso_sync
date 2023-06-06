from . import __version__ as app_version

app_name = "espresso_sync"
app_title = "Espresso Sync"
app_publisher = "Avunu LLC"
app_description = "A Highly-caffeinated Sync Engine for Frappe"
app_email = "mail@avu.nu"
app_license = "MIT"

# app_include_css = "/assets/espresso_sync/css/espresso_sync_custom.css"

# include css file on DocType "Espresso Sync Connection"
# doctype_css = {
#     "Espresso Sync Connection": "public/css/espresso_sync_connection.css"
# }

scheduler_events = {
    "all": [
        "espresso_sync.sync_machine.sync_all"
    ],
    "hourly": [
        "espresso_sync.sync_machine.sync_hourly"
    ],
    "daily": [
        "espresso_sync.sync_machine.sync_daily"
    ],
    "weekly": [
        "espresso_sync.sync_machine.sync_weekly"
    ],
    "monthly": [
        "espresso_sync.sync_machine.sync_monthly"
    ],
    "cron": {
        "*/5 * * * *": [
            "espresso_sync.sync_machine.sync_cron"
        ]
    }
}
