import frappe

from firtrackpro.api.users import provision_client_login as _provision_client_login
from firtrackpro.api.users import provision_client_portal_login as _provision_client_portal_login


@frappe.whitelist(allow_guest=False)
def provision_client_portal_login(**kwargs):
	return _provision_client_portal_login(**kwargs)


@frappe.whitelist(allow_guest=False)
def provision_client_login(**kwargs):
	return _provision_client_login(**kwargs)
