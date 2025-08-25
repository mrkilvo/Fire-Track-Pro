# apps/firtrackpro/firtrackpro/www/portal/sites/index.py
import frappe
from frappe.utils import formatdate

from firtrackpro.portal_utils import build_portal_context, require_login

no_cache = 1

DOC_PROPERTY = "FT Property"
DOC_ASSET = "FT Asset"
DOC_ADDRESS = "Address"


def _format_address(addr_name: str) -> str:
	if not addr_name:
		return ""
	parts = (
		frappe.db.get_value(
			DOC_ADDRESS,
			addr_name,
			["address_line1", "address_line2", "city", "state", "pincode", "country"],
			as_dict=True,
		)
		or {}
	)
	lines = [p for p in [parts.get("address_line1"), parts.get("address_line2")] if p]
	locality = " ".join([p for p in [parts.get("city"), parts.get("state"), parts.get("pincode")] if p])
	if locality:
		lines.append(locality)
	if parts.get("country"):
		lines.append(parts.get("country"))
	return ", ".join(lines)


def _asset_counts_by_property(prop_names):
	if not prop_names:
		return {}
	rows = frappe.db.get_all(
		DOC_ASSET,
		filters={"asset_property": ["in", prop_names]},
		fields=["asset_property as p", "count(name) as n"],
		group_by="asset_property",
		order_by=None,
		limit=None,
		ignore_permissions=1,
	)
	return {r.p: r.n for r in rows}


def get_context(context):
	require_login()

	fields = [
		"name",
		"property_name",
		"property_customer",
		"property_address",
		"modified",
	]
	props = frappe.db.get_all(
		DOC_PROPERTY,
		fields=fields,
		order_by="modified desc",
		limit=200,
		ignore_permissions=1,  # adjust later with proper portal perms
	)

	prop_names = [p.name for p in props]
	asset_counts = _asset_counts_by_property(prop_names)

	context.SITES = [
		{
			"name": p.name,
			"display_name": p.property_name or p.name,
			"customer": p.property_customer or "",
			"address": _format_address(p.property_address),
			"assets": int(asset_counts.get(p.name, 0)),
			"updated": formatdate(p.modified, "d MMM yyyy"),
		}
		for p in props
	]

	context.actions = ["create", "export"]
	context.PAGE_TITLE = "Sites"
	return build_portal_context(context, page_h1="Sites", force_login=False)
