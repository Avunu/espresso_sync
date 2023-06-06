# Copyright (c) 2023, Avunu LLC and contributors
# For license information, please see license.txt

import frappe
# from croniter import croniter
# from datetime import datetime
from crontab import CronSlices
from espresso_sync.sync_machine import process_sync

def sync_all():
    sync_connections = frappe.get_all("Espresso Sync Connection", filters={"enabled": 1, "sync_frequency": "all"})
    for sync_connection in sync_connections:
        process_sync(frappe.get_doc("Espresso Sync Connection", sync_connection.name))

def sync_hourly():
    sync_connections = frappe.get_all("Espresso Sync Connection", filters={"enabled": 1, "sync_frequency": "hourly"})
    for sync_connection in sync_connections:
        process_sync(frappe.get_doc("Espresso Sync Connection", sync_connection.name))

def sync_daily():
    sync_connections = frappe.get_all("Espresso Sync Connection", filters={"enabled": 1, "sync_frequency": "daily"})
    for sync_connection in sync_connections:
        process_sync(frappe.get_doc("Espresso Sync Connection", sync_connection.name))

def sync_weekly():
    sync_connections = frappe.get_all("Espresso Sync Connection", filters={"enabled": 1, "sync_frequency": "weekly"})
    for sync_connection in sync_connections:
        process_sync(frappe.get_doc("Espresso Sync Connection", sync_connection.name))

def sync_monthly():
    sync_connections = frappe.get_all("Espresso Sync Connection", filters={"enabled": 1, "sync_frequency": "monthly"})
    for sync_connection in sync_connections:
        process_sync(frappe.get_doc("Espresso Sync Connection", sync_connection.name))

def sync_cron():
    sync_connections = frappe.get_all("Espresso Sync Connection", filters={"enabled": 1, "sync_frequency": "cron"})
    for sync_connection in sync_connections:
        cron_string = sync_connection.cron_string
        if cron_string:
            schedule = CronSlices.from_string(cron_string)
            if schedule.should_run_now():
                process_sync(frappe.get_doc("Espresso Sync Connection", sync_connection.name))

