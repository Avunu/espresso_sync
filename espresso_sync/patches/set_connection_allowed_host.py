# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""Fill in each Connection's Allowed Host, the one host its credentials are now sent to,
from the URLs it already requests: the API Domain, or the domain every shot overrides it
with when they all agree. A Connection whose shots go to several hosts gets the API
Domain's; requests to the others go without credentials until the host is changed."""

import frappe

from espresso_sync.utils.safe_fetch import host_of

CONNECTION = "Espresso Sync Connection"
SHOT = "Espresso Sync Connection Shot"


def connection_hosts(connection) -> list[str]:
	"""The hosts the Connection's shots send requests to, the API Domain's first."""
	hosts = []
	shots = frappe.get_all(
		SHOT,
		filters={"parent": connection.name, "parenttype": CONNECTION},
		fields=["override_api_domain", "api_domain"],
	)
	if not shots or any(not shot.override_api_domain for shot in shots):
		hosts.append(host_of(connection.api_domain))
	hosts.extend(host_of(shot.api_domain) for shot in shots if shot.override_api_domain)
	return list(dict.fromkeys(host for host in hosts if host))


def allowed_host_for(connection) -> str:
	hosts = connection_hosts(connection)
	if len(hosts) == 1:
		return hosts[0]
	return host_of(connection.api_domain)


def execute():
	for connection in frappe.get_all(
		CONNECTION,
		filters={"allowed_host": ["is", "not set"]},
		fields=["name", "api_domain"],
	):
		allowed_host = allowed_host_for(connection)
		if allowed_host:
			frappe.db.set_value(
				CONNECTION, connection.name, "allowed_host", allowed_host, update_modified=False
			)
