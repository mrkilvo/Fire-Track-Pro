import frappe


def _has_field(doctype: str, fieldname: str) -> bool:
	try:
		meta = frappe.get_meta(doctype)
		return bool(meta.get_field(fieldname))
	except Exception:
		return False


def _get_customer_name(customer_name_or_id: str | None) -> str:
	if not customer_name_or_id:
		return ""
	rows = frappe.get_all(
		"Customer",
		filters={"name": customer_name_or_id},
		fields=["customer_name"],
		limit=1,
	)
	return rows[0]["customer_name"] if rows else customer_name_or_id


def _addr_from_address_docname(ad_name: str | None):
	"""Fetch Address fields safely, only selecting columns that exist on this site."""
	if not ad_name:
		return {
			"line1": "",
			"line2": "",
			"suburb": "",
			"state": "",
			"postcode": "",
			"country": "Australia",
			"lat": None,
			"lng": None,
		}

	base_fields = [
		"address_line1",
		"address_line2",
		"city",
		"state",
		"pincode",
		"country",
	]
	optional = []
	if _has_field("Address", "latitude"):
		optional.append("latitude")
	if _has_field("Address", "longitude"):
		optional.append("longitude")

	fields = base_fields + optional
	a = frappe.get_all("Address", filters={"name": ad_name}, fields=fields, limit=1)
	if not a:
		return {
			"line1": "",
			"line2": "",
			"suburb": "",
			"state": "",
			"postcode": "",
			"country": "Australia",
			"lat": None,
			"lng": None,
		}
	a = a[0]
	return {
		"line1": a.get("address_line1") or "",
		"line2": a.get("address_line2") or "",
		"suburb": a.get("city") or "",
		"state": a.get("state") or "",
		"postcode": a.get("pincode") or "",
		"country": a.get("country") or "Australia",
		"lat": a.get("latitude") if "latitude" in a else None,
		"lng": a.get("longitude") if "longitude" in a else None,
	}


def _contacts_for_property(prop_name: str):
	# Contact linked via Dynamic Link child table
	contacts = frappe.get_all(
		"Contact",
		filters=[
			["Dynamic Link", "link_doctype", "=", "FT Property"],
			["Dynamic Link", "link_name", "=", prop_name],
		],
		fields=[
			"name",
			"first_name",
			"last_name",
			"email_id",
			"phone",
			"mobile_no",
			"designation",
			"is_primary_contact",
			"modified",
		],
		# 👇 pin the table to avoid "Column 'modified' in ORDER BY is ambiguous"
		order_by="is_primary_contact desc, `tabContact`.modified desc",
		limit_page_length=100,
	)
	out = []
	for c in contacts:
		fullname = (c.get("first_name") or "") + ((" " + c.get("last_name")) if c.get("last_name") else "")
		out.append(
			{
				"name": fullname.strip(),
				"role": c.get("designation") or "",
				"phone": c.get("phone") or c.get("mobile_no") or "",
				"email": c.get("email_id") or "",
				"is_primary": c.get("is_primary_contact") or 0,
			}
		)
	return out


def _schedules_for_property(prop_name: str):
	rules = frappe.get_all(
		"FT Schedule Rule",
		filters={"schedule_rule_property": prop_name},
		fields=["name", "schedule_rule_frequency", "schedule_rule_next_occurrence"],
		order_by="schedule_rule_next_occurrence asc, creation asc",
		limit_page_length=200,
	)
	return [
		{
			"name": r["name"],
			"name_or_freq": (r.get("schedule_rule_frequency") or "").title(),
			"frequency": r.get("schedule_rule_frequency"),
			"next": (
				str(r["schedule_rule_next_occurrence"]) if r.get("schedule_rule_next_occurrence") else ""
			),
		}
		for r in rules
	]


def _credentials_badges(prop_name: str):
	meta = frappe.get_meta("FT Property")
	if not meta.get_field("property_credentials"):
		return []
	cred = frappe.db.get_all(
		"FT Property Credential Requirement",
		filters={"parenttype": "FT Property", "parent": prop_name},
		fields=[
			"property_credential_type",
			"property_credential_validity_days",
			"property_credential_blocking",
			"property_credential_notes",
		],
		order_by="idx asc",
	)
	labels = {"Police Check": "Police Check", "WWCC": "WWCC", "Other": "Other"}
	out = []
	for r in cred:
		title = labels.get(r["property_credential_type"], r["property_credential_type"])
		suffix = ""
		if r.get("property_credential_validity_days"):
			suffix = f"(valid {r['property_credential_validity_days']}d)"
		out.append({"name": title, "expires": suffix})
	return out


def _normalize_property_from_doc(d):
	a = _addr_from_address_docname(d.property_address)
	access = {}
	if getattr(d, "property_access", None):
		acc = frappe.get_all(
			"FT Property Access",
			filters={"name": d.property_access},
			fields=["property_access_alarm_panel", "property_access_parking"],
			limit=1,
		)
		if acc:
			access = {
				"instructions": acc[0].get("property_access_alarm_panel") or "",
				"after_hours": acc[0].get("property_access_parking") or "",
			}

	return {
		"name": d.name,
		"display_name": d.property_name or d.name,
		"client": {
			"name": _get_customer_name(d.property_customer),
			"id": d.property_customer or "",
		},
		"address": {
			"line1": a["line1"],
			"line2": a["line2"],
			"suburb": a["suburb"],
			"state": a["state"],
			"postcode": a["postcode"],
			"country": a["country"],
		},
		"lat": d.property_lat or a["lat"],
		"lng": d.property_lng or a["lng"],
		"notes": d.property_notes or "",
		"contract": {},
		"building": {},
		"contacts": _contacts_for_property(d.name),
		"schedules": _schedules_for_property(d.name),
		"accreditations": _credentials_badges(d.name),
		"access": access,
		"billing": {},
		"firelink_linked": False,
	}


def get_context(context):
	name = frappe.form_dict.get("name")
	if not name:
		frappe.throw("Missing property name")

	doc = frappe.get_doc("FT Property", name)
	context.property = _normalize_property_from_doc(doc)

	# --- Assets: show label + type label (hide internal docname) ---
	assets_raw = frappe.get_all(
		"FT Asset",
		filters={"asset_property": name},
		fields=[
			"name",
			"asset_type",
			"asset_label",
			"asset_identifier",
			"asset_status",
		],
		limit=500,
	)
	# Map FT Asset Type -> asset_type_label
	type_names = list({a["asset_type"] for a in assets_raw if a.get("asset_type")})
	type_label_map = {}
	if type_names:
		trows = frappe.get_all(
			"FT Asset Type",
			filters={"name": ["in", type_names]},
			fields=["name", "asset_type_label"],
		)
		type_label_map = {t["name"]: (t.get("asset_type_label") or t["name"]) for t in trows}

	context.assets = [
		{
			# keep id if you need to link later, but don't render it
			"id": a["name"],
			"name": a.get("asset_label") or "",
			"identifier": a.get("asset_identifier") or "",
			"type": type_label_map.get(a.get("asset_type"), a.get("asset_type") or ""),
			"status": a.get("asset_status") or "",
		}
		for a in assets_raw
	]

	jobs = frappe.get_all(
		"FT Job",
		filters={"job_property": name},
		fields=["name", "job_title", "job_status", "job_scheduled_start"],
		limit=100,
		order_by="job_scheduled_start desc",
	)
	context.tasks = [
		{
			"id": j["name"],
			"title": j.get("job_title", "") or j["name"],
			"status": j.get("job_status", ""),
			"when": (str(j.get("job_scheduled_start") or "")[:16]),
		}
		for j in jobs
	]

	dq = frappe.get_all(
		"FT Defect",
		filters={"defect_property": name},
		fields=["name", "defect_description", "defect_quotation", "defect_status"],
		limit=50,
		order_by="modified desc",
	)
	context.defect_quotes = [
		{
			"id": d["name"],
			"title": d.get("defect_description", ""),
			"amount": None,
			"status": d.get("defect_status", ""),
		}
		for d in dq
	]

	context.service_quotes = []

	context.documents = frappe.get_all(
		"FT Document Vault",
		filters={"document_vault_property": name},
		fields=[
			"document_vault_title as name",
			"document_vault_file as url",
			"document_vault_version",
		],
		limit=100,
	)

	context.timeline = []
	context.maptiler_key = ""
	return context
