import frappe

from firtrackpro.api.users import provision_client_login as _provision_client_login
from firtrackpro.api.users import provision_client_portal_login as _provision_client_portal_login


def _clean_kwargs(kwargs):
	data = dict(kwargs or {})
	for key in ("cmd", "method", "data"):
		data.pop(key, None)
	return data


@frappe.whitelist(allow_guest=False)
def provision_client_portal_login(**kwargs):
	return _provision_client_portal_login(**_clean_kwargs(kwargs))


@frappe.whitelist(allow_guest=False)
def provision_client_login(**kwargs):
	return _provision_client_login(**_clean_kwargs(kwargs))
