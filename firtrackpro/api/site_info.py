# apps/firtrackpro/firtrackpro/api/site_info.py
import frappe


@frappe.whitelist()
def get_site():
	"""Return the current Frappe site (used to pick the Socket.IO namespace)."""
	return {"site": frappe.local.site}
