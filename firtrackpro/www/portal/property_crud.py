import json

import frappe
from frappe import _

DOC_PROPERTY = "FT Property"
DOC_ASSET = "FT Asset"
DOC_DEFECT = "FT Defect"
DOC_QUOTATION = "Quotation"
DOC_JOB = "FT Job"  # optional


def _as_json(d):
	if isinstance(d, str):
		return frappe.parse_json(d)
	return d


# ---------- Property updates (NO address change) ----------


@frappe.whitelist(methods=["POST"])
def update_property(name: str, updates: dict | str):
	"""Update property_name, property_notes, property_lat, property_lng. Address is NOT changed."""
	if not name:
		frappe.throw(_("Missing property name"))
	if not frappe.db.exists(DOC_PROPERTY, name):
		frappe.throw(_("Property not found"))
	updates = _as_json(updates) or {}
	fields = ["property_name", "property_notes", "property_lat", "property_lng"]
	vals = {k: updates.get(k) for k in fields if k in updates}
	if not vals:
		return "ok"
	frappe.db.set_value(DOC_PROPERTY, name, vals)  # updates modified
	return "ok"


@frappe.whitelist(methods=["POST"])
def update_access(name: str, updates: dict | str):
	"""Update access/parking fields on the property."""
	if not name:
		frappe.throw(_("Missing property name"))
	if not frappe.db.exists(DOC_PROPERTY, name):
		frappe.throw(_("Property not found"))
	updates = _as_json(updates) or {}
	fields = [
		"property_access_keysafe_code",
		"property_access_gate_code",
		"property_access_alarm_panel",
		"property_access_parking",
	]
	vals = {k: updates.get(k) for k in fields if k in updates}
	if vals:
		frappe.db.set_value(DOC_PROPERTY, name, vals)
	return "ok"


# ---------- Contacts (simple API) ----------


@frappe.whitelist()
def get_contacts(property_name: str):
	"""Return denormalized contacts for the property (from child table if present)."""
	if not property_name or not frappe.db.exists(DOC_PROPERTY, property_name):
		return []
	# Flexible: child table may be named property_contacts with these columns.
	if frappe.db.has_column(DOC_PROPERTY, "property_contacts"):
		# fallback to dynamic fetch via child table API
		rows = frappe.get_all(
			doctype=f"{DOC_PROPERTY} Contact",
			filters={f"{DOC_PROPERTY.replace(' ','_').lower()}_parent": property_name}
			if frappe.db.has_column(
				f"{DOC_PROPERTY} Contact", f"{DOC_PROPERTY.replace(' ','_').lower()}_parent"
			)
			else {"parent": property_name},
			fields=[
				"name",
				"parent",
				"property_contact_contact",
				"property_contact_role",
				"property_contact_is_primary",
				"property_contact_phone",
				"property_contact_email",
			],
			limit=500,
			ignore_permissions=1,
		)
		out = []
		for r in rows:
			# Expand Contact if exists
			cdoc = {}
			cname = r.get("property_contact_contact")
			if cname and frappe.db.exists("Contact", cname):
				cdoc = (
					frappe.db.get_value(
						"Contact",
						cname,
						["name", "first_name", "last_name", "email_id", "mobile_no"],
						as_dict=True,
					)
					or {}
				)
			out.append(
				{
					"name": cname or r.get("name"),
					"full_name": " ".join([cdoc.get("first_name", ""), cdoc.get("last_name", "")]).strip()
					or r.get("property_contact_email")
					or r.get("property_contact_phone"),
					"email": r.get("property_contact_email") or cdoc.get("email_id"),
					"phone": r.get("property_contact_phone") or cdoc.get("mobile_no"),
					"role": r.get("property_contact_role") or "other",
					"is_primary": 1 if r.get("property_contact_is_primary") else 0,
				}
			)
		return out
	return []


@frappe.whitelist(methods=["POST"])
def set_contacts_from_blob(property_name: str, blob: str):
	"""
	Replace contacts using a simple text blob:
	"Full Name | Email | Phone | Role | Primary(0/1)" per line.
	Requires a child table `property_contacts` on FT Property with typical columns.
	"""
	if not property_name or not frappe.db.exists(DOC_PROPERTY, property_name):
		frappe.throw(_("Property not found"))

	# If child table not present, no-op
	if not frappe.db.has_column(DOC_PROPERTY, "property_contacts"):
		return "ok"

	# Wipe existing child rows
	doc = frappe.get_doc(DOC_PROPERTY, property_name)
	if hasattr(doc, "property_contacts"):
		doc.set("property_contacts", [])

	for line in (blob or "").splitlines():
		parts = [p.strip() for p in line.split("|")]
		if not any(parts):  # skip empty
			continue
		full, email, phone, role, primary = (parts + ["", "", "", "", "0"])[:5]
		# Best-effort resolve/create Contact
		contact_name = None
		if email:
			contact_name = frappe.db.get_value("Contact", {"email_id": email}, "name")
		if not contact_name and full:
			contact_name = frappe.db.get_value("Contact", {"first_name": full}, "name")
		if not contact_name:
			cdoc = frappe.get_doc(
				{
					"doctype": "Contact",
					"first_name": full or (email or "Contact"),
					"email_id": email,
					"mobile_no": phone,
				}
			)
			cdoc.insert(ignore_permissions=True)
			contact_name = cdoc.name
		doc.append(
			"property_contacts",
			{
				"property_contact_contact": contact_name,
				"property_contact_role": role or "other",
				"property_contact_is_primary": 1 if str(primary).strip() in ("1", "true", "yes") else 0,
				"property_contact_phone": phone or None,
				"property_contact_email": email or None,
			},
		)

	doc.save(ignore_permissions=True)
	return "ok"


# ---------- Assets ----------


@frappe.whitelist()
def get_asset(name: str):
	if not name:
		frappe.throw(_("Missing name"))
	fields = [
		"name",
		"asset_label",
		"asset_type",
		"asset_zone",
		"asset_status",
		"asset_last_tested",
		"asset_next_due",
	]
	# Drop non-existent columns gracefully
	fields = [f for f in fields if f.split(" as ")[0] in ("name",) or frappe.db.has_column(DOC_ASSET, f)]
	d = frappe.db.get_value(DOC_ASSET, name, fields, as_dict=True)
	if not d:
		frappe.throw(_("Not found"))
	return d


@frappe.whitelist(methods=["POST"])
def save_asset(doc: dict | str):
	d = _as_json(doc) or {}
	if d.get("name"):
		# update
		name = d["name"]
		vals = {
			k: v for k, v in d.items() if k not in ("doctype", "name") and frappe.db.has_column(DOC_ASSET, k)
		}
		if vals:
			frappe.db.set_value(DOC_ASSET, name, vals)
		return {"name": name}
	# create
	d["doctype"] = DOC_ASSET
	ins = frappe.get_doc(d)
	ins.insert(ignore_permissions=True)
	return {"name": ins.name}


@frappe.whitelist(methods=["POST"])
def delete_asset(name: str):
	if not name:
		frappe.throw(_("Missing name"))
	frappe.delete_doc(DOC_ASSET, name, ignore_permissions=True, force=1)
	return "ok"


# ---------- Jobs (History) ----------


@frappe.whitelist()
def get_job(name: str):
	if not name:
		frappe.throw(_("Missing name"))
	if not frappe.db.table_exists(DOC_JOB):
		frappe.throw(_("Jobs table not available"))
	wanted = ["name", "job_title", "job_status", "job_required_date", "job_scheduled_start"]
	fields = [f for f in wanted if f.split(" as ")[0] in ("name",) or frappe.db.has_column(DOC_JOB, f)]
	d = frappe.db.get_value(DOC_JOB, name, fields, as_dict=True)
	if not d:
		frappe.throw(_("Not found"))
	return d


@frappe.whitelist(methods=["POST"])
def save_job(doc: dict | str):
	d = _as_json(doc) or {}
	if not frappe.db.table_exists(DOC_JOB):
		frappe.throw(_("Jobs table not available"))
	if d.get("name"):
		name = d["name"]
		vals = {
			k: v for k, v in d.items() if k not in ("doctype", "name") and frappe.db.has_column(DOC_JOB, k)
		}
		if vals:
			frappe.db.set_value(DOC_JOB, name, vals)
		return {"name": name}
	d["doctype"] = DOC_JOB
	ins = frappe.get_doc(d)
	ins.insert(ignore_permissions=True)
	return {"name": ins.name}


@frappe.whitelist(methods=["POST"])
def delete_job(name: str):
	if not name:
		frappe.throw(_("Missing name"))
	if not frappe.db.table_exists(DOC_JOB):
		return "ok"
	frappe.delete_doc(DOC_JOB, name, ignore_permissions=True, force=1)
	return "ok"


# ---------- Quotes ----------


@frappe.whitelist()
def get_quote(name: str):
	if not name:
		frappe.throw(_("Missing name"))
	fields = ["name", "customer", "customer_name", "transaction_date", "valid_till", "status"]
	fields = [f for f in fields if f.split(" as ")[0] in ("name",) or frappe.db.has_column(DOC_QUOTATION, f)]
	d = frappe.db.get_value(DOC_QUOTATION, name, fields, as_dict=True)
	if not d:
		frappe.throw(_("Not found"))
	return d


@frappe.whitelist(methods=["POST"])
def create_quote(values: dict | str):
	v = _as_json(values) or {}
	if not v.get("customer"):
		frappe.throw(_("Customer is required"))
	doc = {
		"doctype": DOC_QUOTATION,
		"customer": v["customer"],
		"transaction_date": v.get("transaction_date"),
		"valid_till": v.get("valid_till"),
		"status": v.get("status"),
	}
	# Link back to property if field exists
	if frappe.db.has_column(DOC_QUOTATION, "quote_property") and v.get("quote_property"):
		doc["quote_property"] = v["quote_property"]
	q = frappe.get_doc(doc)
	q.insert(ignore_permissions=True)
	return {"name": q.name}


@frappe.whitelist(methods=["POST"])
def save_quote(doc: dict | str):
	d = _as_json(doc) or {}
	if not d.get("name"):
		frappe.throw(_("Missing name"))
	vals = {
		k: v for k, v in d.items() if k not in ("name", "doctype") and frappe.db.has_column(DOC_QUOTATION, k)
	}
	if vals:
		frappe.db.set_value(DOC_QUOTATION, d["name"], vals)
	return {"name": d["name"]}


@frappe.whitelist(methods=["POST"])
def delete_quote(name: str):
	if not name:
		frappe.throw(_("Missing name"))
	frappe.delete_doc(DOC_QUOTATION, name, ignore_permissions=True, force=1)
	return "ok"


# ---------- Defects ----------


@frappe.whitelist()
def get_defect(name: str):
	if not name:
		frappe.throw(_("Missing name"))
	if not frappe.db.table_exists(DOC_DEFECT):
		frappe.throw(_("Defects table not available"))
	fields = ["name", "defect_severity", "defect_status", "defect_description", "defect_quotation"]
	fields = [f for f in fields if f.split(" as ")[0] in ("name",) or frappe.db.has_column(DOC_DEFECT, f)]
	d = frappe.db.get_value(DOC_DEFECT, name, fields, as_dict=True)
	if not d:
		frappe.throw(_("Not found"))
	return d


@frappe.whitelist(methods=["POST"])
def save_defect(doc: dict | str):
	d = _as_json(doc) or {}
	if not frappe.db.table_exists(DOC_DEFECT):
		frappe.throw(_("Defects table not available"))
	if d.get("name"):
		name = d["name"]
		vals = {
			k: v for k, v in d.items() if k not in ("doctype", "name") and frappe.db.has_column(DOC_DEFECT, k)
		}
		if vals:
			frappe.db.set_value(DOC_DEFECT, name, vals)
		return {"name": name}
	d["doctype"] = DOC_DEFECT
	ins = frappe.get_doc(d)
	ins.insert(ignore_permissions=True)
	return {"name": ins.name}


@frappe.whitelist(methods=["POST"])
def delete_defect(name: str):
	if not name:
		frappe.throw(_("Missing name"))
	if not frappe.db.table_exists(DOC_DEFECT):
		return "ok"
	frappe.delete_doc(DOC_DEFECT, name, ignore_permissions=True, force=1)
	return "ok"


# ---------- Generic meta-driven schema for FT Asset ----------


def _field_is_portal_editable(df):
	"""Filter to practical fields for the portal editor."""
	# hide read-only, hidden, virtual, table fields etc.
	if getattr(df, "hidden", 0) or getattr(df, "read_only", 0):
		return False
	if df.fieldtype in ("Table", "Table MultiSelect", "HTML", "Button", "Image"):
		return False
	# we mostly want FT namespaced asset_* fields (+ label/name)
	return df.fieldname.startswith("asset_") or df.fieldname in ("asset_label", "asset_name")


@frappe.whitelist()
def asset_form_schema():
	"""Return an ordered list of fields for FT Asset, including select options & link targets."""
	doctype = "FT Asset"
	meta = frappe.get_meta(doctype)
	out = []
	for df in sorted(meta.fields, key=lambda x: x.idx or 0):
		if not _field_is_portal_editable(df):
			continue
		item = {
			"label": df.label,
			"fieldname": df.fieldname,
			"fieldtype": df.fieldtype,
			"reqd": 1 if getattr(df, "reqd", 0) else 0,
			"read_only": 1 if getattr(df, "read_only", 0) else 0,
			"default": getattr(df, "default", None),
		}
		if df.fieldtype == "Select":
			# options may be in df.options as newline separated, or via property setter
			raw = (df.options or "").strip()
			if raw and not raw.startswith("link:") and "\n" in raw:
				item["options"] = [o for o in (raw.splitlines()) if o and o != "Select"]
			else:
				# try property setter
				ps = frappe.db.get_value(
					"Property Setter",
					{"doc_type": doctype, "field_name": df.fieldname, "property": "options"},
					"value",
				)
				if ps:
					item["options"] = [o for o in ps.splitlines() if o and o != "Select"]
		if df.fieldtype == "Link":
			item["link_doctype"] = df.options
		out.append(item)
	# Always include asset_property if present (we set it automatically)
	if frappe.db.has_column(doctype, "asset_property"):
		out.append(
			{
				"label": "Property",
				"fieldname": "asset_property",
				"fieldtype": "Link",
				"link_doctype": "FT Property",
				"reqd": 1,
				"read_only": 1,
			}
		)
	return {"doctype": doctype, "fields": out}


@frappe.whitelist()
def link_search(doctype: str, q: str = "", limit: int = 10):
	"""Generic link-field autocomplete."""
	if not doctype:
		return []
	q = (q or "").strip()
	cond = {}
	if q:
		# Try both name and '..._name' commonly used in masters
		cond = ["or", ["name", "like", f"%{q}%"]]
		# attempt a readable name column
		name_col = None
		for guess in ("asset_type_name", "customer_name", "item_name", "title"):
			if frappe.db.has_column(doctype, guess):
				name_col = guess
				break
		if name_col:
			cond.append([name_col, "like", f"%{q}%"])
	fields = ["name"]
	# include pretty label if available
	for guess in ("asset_type_name", "customer_name", "item_name", "title", "description"):
		if frappe.db.has_column(doctype, guess):
			fields.append(guess)
			break
	rows = frappe.get_all(
		doctype,
		filters=cond or None,
		fields=fields,
		order_by="modified desc",
		limit=limit,
		ignore_permissions=1,
	)
	# normalize 'label'
	for r in rows:
		if len(r) > 1:
			lbl = [v for k, v in r.items() if k != "name" and v]
			r["label"] = lbl[0] if lbl else r["name"]
		else:
			r["label"] = r["name"]
	return rows
