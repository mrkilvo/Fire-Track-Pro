# firtrackpro/www/portal/property_crud.py
import frappe

DOC_PROPERTY = "FT Property"
DOC_ASSET = "FT Asset"
DOC_DEFECT = "FT Defect"
DOC_QUOTATION = "Quotation"
DOC_JOB = "FT Job"

def _as_json(d):
	if isinstance(d, str):
		return frappe.parse_json(d)
	return d

def _exists(dt, name):
	return bool(name and frappe.db.exists(dt, name))

def _safe_cols(dt, cols):
	return [c for c in cols if c.split(" as ")[0] in ("name",) or frappe.db.has_column(dt, c)]

@frappe.whitelist()
def get_overview(name: str):
	if not _exists(DOC_PROPERTY, name):
		frappe.throw("Property not found")
	prop_fields = _safe_cols(DOC_PROPERTY, [
		"name","property_name","property_customer","property_as1851_edition",
		"property_lat","property_lng","property_notes",
		"property_address","property_access_maps"
	])
	for fld in ("firelink_uid","property_firelink_uid"):
		if frappe.db.has_column(DOC_PROPERTY, fld):
			prop_fields.append(fld)
	property_row = frappe.db.get_value(DOC_PROPERTY, name, prop_fields, as_dict=True) or {}
	addr = {}
	addrname = property_row.get("property_address") if frappe.db.has_column(DOC_PROPERTY,"property_address") else None
	if addrname and frappe.db.exists("Address", addrname):
		addr = frappe.db.get_value("Address", addrname, ["name","address_line1","address_line2","city","state","pincode","country"], as_dict=True) or {}
	cust = {}
	custname = property_row.get("property_customer") if frappe.db.has_column(DOC_PROPERTY,"property_customer") else None
	if custname and frappe.db.exists("Customer", custname):
		cust = frappe.db.get_value("Customer", custname, ["name","customer_name","email_id","mobile_no"], as_dict=True) or {}
	contacts = []
	if frappe.db.has_column(DOC_PROPERTY, "property_contacts"):
		rows = frappe.get_all(
			doctype=f"{DOC_PROPERTY} Contact",
			filters={"parent": name},
			fields=["name","property_contact_contact","property_contact_role","property_contact_is_primary","property_contact_phone","property_contact_email"],
			limit=500,
			ignore_permissions=1,
		)
		for r in rows:
			full = None
			if r.get("property_contact_contact") and frappe.db.exists("Contact", r["property_contact_contact"]):
				cd = frappe.db.get_value("Contact", r["property_contact_contact"], ["first_name","last_name"], as_dict=True) or {}
				full = " ".join([cd.get("first_name",""), cd.get("last_name","")]).strip() or None
			contacts.append({
				"full_name": full or r.get("property_contact_email") or r.get("property_contact_phone"),
				"property_contact_email": r.get("property_contact_email"),
				"property_contact_phone": r.get("property_contact_phone"),
				"property_contact_role": r.get("property_contact_role"),
				"property_contact_is_primary": 1 if r.get("property_contact_is_primary") else 0,
			})
	has_access = any(frappe.db.has_column(DOC_PROPERTY, c) for c in [
		"property_access_keysafe_code","property_access_gate_code","property_access_alarm_panel","property_access_parking"
	])
	access_stub = {}
	return {"property": property_row, "address": addr, "customer": cust, "contacts": contacts, "has_access": 1 if has_access else 0, "access": access_stub}

@frappe.whitelist(methods=["POST"])
def update_basic(property_name: str, updates: dict | str):
	if not _exists(DOC_PROPERTY, property_name):
		frappe.throw("Property not found")
	u = _as_json(updates) or {}
	fields = ["property_name","property_as1851_edition","property_lat","property_lng","property_notes"]
	vals = {k: u.get(k) for k in fields if frappe.db.has_column(DOC_PROPERTY, k) and k in u}
	if vals:
		frappe.db.set_value(DOC_PROPERTY, property_name, vals)
	return "ok"

@frappe.whitelist()
def reveal_access(property_name: str):
	if not _exists(DOC_PROPERTY, property_name):
		frappe.throw("Property not found")
	fields = _safe_cols(DOC_PROPERTY, [
		"property_access_keysafe_code","property_access_gate_code","property_access_alarm_panel",
		"property_access_parking","property_access_maps","property_access_last_revealed_on","property_access_last_revealed_by"
	])
	row = frappe.db.get_value(DOC_PROPERTY, property_name, fields, as_dict=True) or {}
	return row

@frappe.whitelist(methods=["POST"])
def update_access(property_name: str, **kwargs):
	if not _exists(DOC_PROPERTY, property_name):
		frappe.throw("Property not found")
	fields = [
		"property_access_keysafe_code","property_access_gate_code","property_access_alarm_panel",
		"property_access_parking","property_access_maps"
	]
	vals = {k: kwargs.get(k) for k in fields if frappe.db.has_column(DOC_PROPERTY,k) and k in kwargs}
	if vals:
		frappe.db.set_value(DOC_PROPERTY, property_name, vals)
	out = reveal_access(property_name)
	return out

@frappe.whitelist(methods=["POST"])
def update_contacts(property_name: str, contacts: list | str):
	if not _exists(DOC_PROPERTY, property_name):
		frappe.throw("Property not found")
	if not frappe.db.has_column(DOC_PROPERTY, "property_contacts"):
		return []
	doc = frappe.get_doc(DOC_PROPERTY, property_name)
	doc.set("property_contacts", [])
	rows = _as_json(contacts) or []
	for r in rows:
		full = (r.get("full_name") or "").strip()
		email = (r.get("email") or "").strip()
		phone = (r.get("phone") or "").strip()
		role = (r.get("role") or "other").strip()
		primary = 1 if r.get("is_primary") else 0
		contact_name = None
		if email:
			contact_name = frappe.db.get_value("Contact", {"email_id": email}, "name")
		if not contact_name and full:
			contact_name = frappe.db.get_value("Contact", {"first_name": full}, "name")
		if not contact_name:
			cdoc = frappe.get_doc({"doctype":"Contact","first_name":full or (email or "Contact"),"email_id":email,"mobile_no":phone})
			cdoc.insert(ignore_permissions=True)
			contact_name = cdoc.name
		doc.append("property_contacts",{
			"property_contact_contact": contact_name,
			"property_contact_role": role,
			"property_contact_is_primary": primary,
			"property_contact_phone": phone or None,
			"property_contact_email": email or None
		})
	doc.save(ignore_permissions=True)
	out = []
	for ch in doc.get("property_contacts") or []:
		out.append({
			"full_name": full if (full:=frappe.db.get_value("Contact", ch.property_contact_contact, "first_name")) else ch.property_contact_email or ch.property_contact_phone,
			"property_contact_role": ch.property_contact_role,
			"property_contact_is_primary": 1 if ch.property_contact_is_primary else 0,
			"property_contact_phone": ch.property_contact_phone,
			"property_contact_email": ch.property_contact_email
		})
	return out

@frappe.whitelist()
def get_asset_form_options(property_name: str):
	types = []
	if frappe.db.table_exists("FT Asset Type"):
		types = frappe.get_all("FT Asset Type", fields=["name","asset_type_label","asset_type_standard"], order_by="asset_type_label asc", limit=1000, ignore_permissions=1)
	zones = []
	if frappe.db.table_exists("FT Property Zone"):
		zones = frappe.get_all("FT Property Zone", filters={"property_zone_property": property_name} if frappe.db.has_column("FT Property Zone","property_zone_property") else None, fields=["name","property_zone_title"], order_by="property_zone_title asc", limit=1000, ignore_permissions=1)
	standards = []
	if frappe.db.table_exists("FT Standard"):
		standards = frappe.get_all("FT Standard", fields=["name","standard_label"], order_by="standard_label asc", ignore_permissions=1)
	status_options = []
	if frappe.db.has_column(DOC_ASSET, "asset_status"):
		ps = frappe.db.get_value("Property Setter", {"doc_type": DOC_ASSET, "field_name": "asset_status", "property": "options"}, "value")
		if ps:
			status_options = [o for o in ps.splitlines() if o and o!="Select"]
		else:
			status_options = ["active","inactive","decommissioned"]
	return {"types": types, "zones": zones, "standards": standards, "status_options": status_options}

@frappe.whitelist()
def list_assets(property_name: str):
	f = {"asset_property": property_name} if frappe.db.has_column(DOC_ASSET,"asset_property") else None
	fields = _safe_cols(DOC_ASSET, [
		"name","asset_label","asset_type","asset_status","asset_zone","asset_last_tested","asset_next_due","asset_standard",
		"asset_install_date","asset_make","asset_model","asset_serial","asset_identifier",
		"asset_location_level","asset_location_area","asset_location_riser","asset_location_cupboard","asset_location_room","asset_location_notes"
	])
	rows = frappe.get_all(DOC_ASSET, filters=f, fields=fields, order_by="modified desc", limit=1000, ignore_permissions=1)
	if frappe.db.table_exists("FT Asset Type"):
		lbls = {r.name: r.asset_type_label for r in frappe.get_all("FT Asset Type", fields=["name","asset_type_label"], ignore_permissions=1)}
		for r in rows:
			if r.get("asset_type") in lbls:
				r["asset_type_label"] = lbls[r["asset_type"]]
	if frappe.db.table_exists("FT Property Zone"):
		zlbl = {r.name: r.property_zone_title for r in frappe.get_all("FT Property Zone", fields=["name","property_zone_title"], ignore_permissions=1)}
		for r in rows:
			if r.get("asset_zone") in zlbl:
				r["zone_title"] = zlbl[r["asset_zone"]]
	return rows

@frappe.whitelist(methods=["POST"])
def create_asset(**kwargs):
	if not kwargs.get("asset_property"):
		frappe.throw("asset_property is required")
	d = {k:v for k,v in kwargs.items() if k in frappe.get_meta(DOC_ASSET).get_valid_columns()}
	d["doctype"] = DOC_ASSET
	doc = frappe.get_doc(d)
	doc.insert(ignore_permissions=True)
	return {"name": doc.name}

@frappe.whitelist(methods=["POST"])
def update_asset(**kwargs):
	name = kwargs.get("name")
	if not _exists(DOC_ASSET, name):
		frappe.throw("Asset not found")
	vals = {k:v for k,v in kwargs.items() if k not in ("name","doctype") and frappe.db.has_column(DOC_ASSET, k)}
	if vals:
		frappe.db.set_value(DOC_ASSET, name, vals)
	return {"name": name}

@frappe.whitelist(methods=["POST"])
def delete_asset(name: str):
	if not _exists(DOC_ASSET, name):
		return "ok"
	frappe.delete_doc(DOC_ASSET, name, ignore_permissions=True, force=1)
	return "ok"

@frappe.whitelist()
def list_history(property_name: str):
	if not frappe.db.table_exists(DOC_JOB):
		return []
	f = [["job_property","=",property_name]] if frappe.db.has_column(DOC_JOB,"job_property") else [["property","=",property_name]] if frappe.db.has_column(DOC_JOB,"property") else None
	fields = _safe_cols(DOC_JOB, ["name","job_title","job_status","job_required_date","job_scheduled_start","modified"])
	return frappe.get_all(DOC_JOB, filters=f, fields=fields, order_by="modified desc", limit=500, ignore_permissions=1)

@frappe.whitelist(methods=["POST"])
def create_job(property_name: str, job_title: str = "", job_required_date: str | None = None, job_instance: str | None = None):
	if not frappe.db.table_exists(DOC_JOB):
		frappe.throw("Jobs table not available")
	doc = {"doctype": DOC_JOB}
	if frappe.db.has_column(DOC_JOB,"job_property"):
		doc["job_property"] = property_name
	elif frappe.db.has_column(DOC_JOB,"property"):
		doc["property"] = property_name
	if frappe.db.has_column(DOC_JOB,"job_title"):
		doc["job_title"] = job_title
	if frappe.db.has_column(DOC_JOB,"job_required_date"):
		doc["job_required_date"] = job_required_date
	if frappe.db.has_column(DOC_JOB,"job_instance"):
		doc["job_instance"] = job_instance
	j = frappe.get_doc(doc)
	j.insert(ignore_permissions=True)
	return {"name": j.name}

@frappe.whitelist()
def list_quotes(property_name: str):
	f = None
	if frappe.db.has_column(DOC_QUOTATION,"quote_property"):
		f = {"quote_property": property_name}
	fields = _safe_cols(DOC_QUOTATION, ["name","customer","customer_name","transaction_date","valid_till","grand_total","status"])
	return frappe.get_all(DOC_QUOTATION, filters=f, fields=fields, order_by="modified desc", limit=500, ignore_permissions=1)

@frappe.whitelist(methods=["POST"])
def create_quote(property_name: str, valid_till: str | None = None, notes: str | None = None):
	if not frappe.db.table_exists(DOC_QUOTATION):
		frappe.throw("Quotation DocType not available")
	customer = None
	if frappe.db.has_column(DOC_PROPERTY,"property_customer"):
		customer = frappe.db.get_value(DOC_PROPERTY, property_name, "property_customer")
	if not customer:
		frappe.throw("Customer is required on property")
	doc = {"doctype": DOC_QUOTATION, "customer": customer}
	if frappe.db.has_column(DOC_QUOTATION,"valid_till"):
		doc["valid_till"] = valid_till
	if frappe.db.has_column(DOC_QUOTATION,"quote_property"):
		doc["quote_property"] = property_name
	if frappe.db.has_column(DOC_QUOTATION,"remarks") and notes:
		doc["remarks"] = notes
	q = frappe.get_doc(doc)
	q.insert(ignore_permissions=True)
	return {"name": q.name}

@frappe.whitelist()
def list_defects(property_name: str):
	if not frappe.db.table_exists(DOC_DEFECT):
		return []
	f = {"defect_property": property_name} if frappe.db.has_column(DOC_DEFECT,"defect_property") else None
	fields = _safe_cols(DOC_DEFECT, ["name","defect_severity","defect_status","defect_description","defect_quotation","modified"])
	return frappe.get_all(DOC_DEFECT, filters=f, fields=fields, order_by="modified desc", limit=500, ignore_permissions=1)

@frappe.whitelist(methods=["POST"])
def create_defect(property_name: str, defect_asset: str | None = None, defect_severity: str | None = None, defect_description: str | None = None):
	if not frappe.db.table_exists(DOC_DEFECT):
		frappe.throw("Defects table not available")
	doc = {"doctype": DOC_DEFECT}
	if frappe.db.has_column(DOC_DEFECT,"defect_property"):
		doc["defect_property"] = property_name
	if frappe.db.has_column(DOC_DEFECT,"defect_asset") and defect_asset:
		doc["defect_asset"] = defect_asset
	if frappe.db.has_column(DOC_DEFECT,"defect_severity") and defect_severity:
		doc["defect_severity"] = defect_severity
	if frappe.db.has_column(DOC_DEFECT,"defect_description") and defect_description:
		doc["defect_description"] = defect_description
	d = frappe.get_doc(doc)
	d.insert(ignore_permissions=True)
	return {"name": d.name}

@frappe.whitelist(methods=["POST"])
def update_defect(name: str, **kwargs):
	if not _exists(DOC_DEFECT, name):
		frappe.throw("Defect not found")
	vals = {k:v for k,v in kwargs.items() if frappe.db.has_column(DOC_DEFECT, k)}
	if vals:
		frappe.db.set_value(DOC_DEFECT, name, vals)
	return {"name": name}

@frappe.whitelist(methods=["POST"])
def delete_defect(name: str):
	if not _exists(DOC_DEFECT, name):
		return "ok"
	frappe.delete_doc(DOC_DEFECT, name, ignore_permissions=True, force=1)
	return "ok"
