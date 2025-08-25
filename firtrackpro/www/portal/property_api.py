# firtrackpro/portal/property_api.py
import frappe
from frappe import _
from frappe.utils import now_datetime

DOC_PROPERTY = "FT Property"
DOC_ASSET = "FT Asset"
DOC_PROPERTY_ACCESS = "FT Property Access"
DOC_AUDIT_LOG = "FT Audit Log"
DOC_JOB = "FT Job"
DOC_DEFECT = "FT Defect"
DOC_ADDRESS = "Address"
DOC_CUSTOMER = "Customer"
DOC_QUOTATION = "Quotation"


def _coalesce_access_name(prop_doc):
	if getattr(prop_doc, "property_access", None):
		return prop_doc.property_access
	return frappe.db.get_value(DOC_PROPERTY_ACCESS, {"property_access_property": prop_doc.name}, "name")


@frappe.whitelist()
def get_property(name: str):
	prop = frappe.get_doc(DOC_PROPERTY, name)
	out = {
		"name": prop.name,
		"property_name": prop.property_name,
		"property_customer": prop.property_customer,
		"property_address": prop.property_address,
		"property_as1851_edition": prop.property_as1851_edition,
		"property_lat": prop.property_lat,
		"property_lng": prop.property_lng,
		"property_notes": prop.property_notes,
	}

	if prop.property_address:
		addr_fields = [
			"address_title",
			"address_line1",
			"address_line2",
			"city",
			"state",
			"pincode",
			"country",
		]
		out["address"] = frappe.db.get_value(DOC_ADDRESS, prop.property_address, addr_fields, as_dict=True)

	if prop.property_customer:
		out["customer"] = frappe.db.get_value(
			DOC_CUSTOMER, prop.property_customer, ["customer_name"], as_dict=True
		)

	access_name = _coalesce_access_name(prop)
	out["has_access"] = bool(access_name)
	out["property_access_name"] = access_name
	return out


@frappe.whitelist()
def get_assets(property_name: str, limit: int = 100):
	return frappe.db.get_all(
		DOC_ASSET,
		filters={"asset_property": property_name},
		fields=[
			"name",
			"asset_label",
			"asset_type",
			"asset_status",
			"asset_zone",
			"asset_last_tested",
			"asset_next_due",
		],
		order_by="modified desc",
		limit=limit,
	)


@frappe.whitelist()
def get_history(property_name: str, limit: int = 50):
	return frappe.db.get_all(
		DOC_JOB,
		filters={"job_property": property_name},
		fields=["name", "job_title", "job_status", "job_required_date", "job_scheduled_start", "modified"],
		order_by="modified desc",
		limit=limit,
	)


@frappe.whitelist()
def get_defects(property_name: str, limit: int = 100):
	return frappe.db.get_all(
		DOC_DEFECT,
		filters={"defect_property": property_name},
		fields=[
			"name",
			"defect_severity",
			"defect_status",
			"defect_description",
			"defect_template",
			"defect_quotation",
			"modified",
		],
		order_by="modified desc",
		limit=limit,
	)


@frappe.whitelist()
def get_quotes(property_name: str, limit: int = 50):
	rows = frappe.db.get_all(
		DOC_DEFECT,
		filters={"defect_property": property_name, "defect_quotation": ["is", "set"]},
		fields=["defect_quotation"],
		limit=500,
	)
	quote_names = sorted({r["defect_quotation"] for r in rows if r.get("defect_quotation")})
	if not quote_names:
		return []
	out = []
	for qn in quote_names[:limit]:
		q = frappe.db.get_value(
			DOC_QUOTATION,
			qn,
			["name", "status", "grand_total", "transaction_date", "valid_till", "customer_name"],
			as_dict=True,
		)
		if q:
			out.append(q)
	return out


@frappe.whitelist()
def reveal_access(property_name: str, reason: str | None = None):
	prop = frappe.get_doc(DOC_PROPERTY, property_name)
	access_name = _coalesce_access_name(prop)
	if not access_name:
		frappe.throw(_("No access details recorded for this property"), title=_("Not Found"))

	access = frappe.get_doc(DOC_PROPERTY_ACCESS, access_name)

	if not frappe.has_permission(doctype=DOC_PROPERTY_ACCESS, doc=access, ptype="read"):
		frappe.throw(_("You do not have permission to view access details"), frappe.PermissionError)

	user = frappe.session.user
	access.db_set("property_access_last_revealed_by", user, update_modified=False)
	access.db_set("property_access_last_revealed_on", now_datetime(), update_modified=False)

	try:
		frappe.get_doc(
			{
				"doctype": DOC_AUDIT_LOG,
				"audit_log_action": "view_secret",
				"audit_log_target_doctype": DOC_PROPERTY_ACCESS,
				"audit_log_target_name": access.name,
				"audit_log_reason": reason or "Portal reveal",
				"audit_log_user": user,
			}
		).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "FT Property Access reveal: audit log failed")

	return {
		"property_access_keysafe_code": access.property_access_keysafe_code,
		"property_access_gate_code": access.property_access_gate_code,
		"property_access_alarm_panel": access.property_access_alarm_panel,
		"property_access_parking": access.property_access_parking,
		"property_access_maps": access.property_access_maps,
		"property_access_last_revealed_by": access.property_access_last_revealed_by,
		"property_access_last_revealed_on": access.property_access_last_revealed_on,
	}
