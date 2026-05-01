import frappe

from firtrackpro.api.users import provision_contractor_login as _provision_contractor_login
from firtrackpro.api.users import provision_contractor_portal_login as _provision_contractor_portal_login


@frappe.whitelist(allow_guest=False)
def provision_contractor_portal_login(**kwargs):
	return _provision_contractor_portal_login(**kwargs)


@frappe.whitelist(allow_guest=False)
def provision_contractor_login(**kwargs):
	return _provision_contractor_login(**kwargs)
