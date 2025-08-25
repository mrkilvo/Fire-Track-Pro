# apps/firtrackpro/firtrackpro/www/portal/sites/new/index.py
import json
from urllib.parse import quote

import frappe

from firtrackpro.portal_utils import build_portal_context, require_login

no_cache = 1

DOC_PROPERTY = "FT Property"
DOC_ADDRESS = "Address"
DOC_CUSTOMER = "Customer"  # standard ERPNext


def _redirect_to_view(name: str):
	frappe.local.flags.redirect_location = f"/portal/sites/view?name={quote(name)}"
	raise frappe.Redirect


def _ensure_address_from_selection(
	address_json: str, property_name: str, property_customer: str | None
) -> str:
	"""
	Create an Address doc from the selected suggestion JSON.
	Returns Address.name
	"""
	if not address_json:
		return ""

	try:
		data = json.loads(address_json)
	except Exception:
		frappe.throw("Invalid address payload")

	# Build Address doc
	addr_title = property_name or (data.get("label") or "Site Address")
	doc = frappe.get_doc(
		{
			"doctype": DOC_ADDRESS,
			"address_title": addr_title,
			"address_type": "Other",
			"address_line1": data.get("address_line1") or data.get("label")[:140],
			"address_line2": data.get("address_line2"),
			"city": data.get("city"),
			"state": data.get("state"),
			"pincode": data.get("pincode"),
			"country": data.get("country") or "Australia",
		}
	)

	# Link to Customer if provided
	if property_customer:
		doc.append("links", {"link_doctype": DOC_CUSTOMER, "link_name": property_customer})

	doc.insert(ignore_permissions=False)
	return doc.name


def get_context(context):
	require_login()
	context.PAGE_TITLE = "New Site"

	if frappe.request and frappe.request.method == "POST":
		if not frappe.has_permission(DOC_PROPERTY, ptype="create"):
			frappe.throw("Not permitted to create Sites", frappe.PermissionError)

		fm = frappe.form_dict or {}
		prop_name = (fm.get("property_name") or "").strip()
		prop_customer = (fm.get("property_customer") or "").strip() or None
		prop_as1851 = (fm.get("property_as1851_edition") or "").strip() or None
		prop_notes = fm.get("property_notes") or ""
		prop_lat = fm.get("property_lat") or None
		prop_lng = fm.get("property_lng") or None

		# If the user picked a suggestion, we get address_json and create Address
		address_json = fm.get("address_json")
		addr_docname = ""
		if address_json:
			addr_docname = _ensure_address_from_selection(address_json, prop_name, prop_customer)
		else:
			# fallback: direct Address name typed (optional)
			addr_docname = (fm.get("property_address") or "").strip() or ""

		# Insert FT Property
		prop = frappe.get_doc(
			{
				"doctype": DOC_PROPERTY,
				"property_name": prop_name,
				"property_customer": prop_customer,
				"property_address": addr_docname,
				"property_as1851_edition": prop_as1851,
				"property_notes": prop_notes,
				"property_lat": prop_lat or None,
				"property_lng": prop_lng or None,
			}
		)
		prop.insert(ignore_permissions=False)
		frappe.db.commit()
		_redirect_to_view(prop.name)

	# GET: render empty form
	return build_portal_context(context, page_h1="New Site", force_login=False)
