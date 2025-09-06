import frappe
from frappe.utils.data import cint
from firtrackpro.portal_utils import build_portal_context

no_cache = 1

def get_context(context):
	context.actions = ["create"]
	context.PAGE_TITLE = "Customers"
	return build_portal_context(context, page_h1="Customers", force_login=True)

def _doctype_exists(dt: str) -> bool:
	try:
		return bool(frappe.db.exists("DocType", dt))
	except Exception:
		return False

@frappe.whitelist(allow_guest=False)
def customer_meta():
	if not _doctype_exists("Customer"):
		frappe.throw("ERPNext Customer doctype not found.")
	meta = frappe.get_meta("Customer")
	fields = []
	for df in meta.fields:
		if df.hidden or df.read_only or df.fieldtype in ("Section Break","Column Break","Fold","HTML","Button","Table MultiSelect"):
			continue
		fields.append({
			"fieldname": df.fieldname,
			"label": df.label,
			"fieldtype": df.fieldtype,
			"options": df.options,
			"reqd": int(df.reqd or 0),
			"default": df.default,
			"in_list_view": int(df.in_list_view or 0),
		})
	return {
		"doctype": "Customer",
		"title_field": getattr(meta, "title_field", "customer_name"),
		"fields": fields
	}

@frappe.whitelist(allow_guest=False)
def list_customers(q: str | None = None, start: int = 0, page_length: int = 25):
	start = cint(start or 0)
	page_length = min(cint(page_length or 25), 200)
	q = (q or "").strip()
	if not _doctype_exists("Customer"):
		frappe.throw("ERPNext Customer doctype not found.")
	fields = ["name","customer_name","customer_type","email_id","disabled","modified"]
	or_filters = []
	if q:
		like = f"%{q}%"
		or_filters = [
			["Customer","name","like",like],
			["Customer","customer_name","like",like],
			["Customer","email_id","like",like],
			["Customer","customer_type","like",like],
		]
	rows = frappe.db.get_list(
		"Customer",
		fields=fields,
		or_filters=or_filters,
		order_by="modified desc",
		limit_start=start,
		limit_page_length=page_length,
		ignore_permissions=1,
		as_list=False,
	)
	total = None if q else frappe.db.count("Customer")
	return {"rows": rows, "has_more": len(rows)==page_length, "total": total}

@frappe.whitelist(allow_guest=False)
def get_customer(name: str):
	if not _doctype_exists("Customer"):
		frappe.throw("ERPNext Customer doctype not found.")
	if not frappe.db.exists("Customer", name):
		frappe.throw("Customer not found.")
	doc = frappe.get_doc("Customer", name)
	out = {"name": doc.name}
	meta = frappe.get_meta("Customer")
	for df in meta.fields:
		if df.hidden or df.fieldtype in ("Section Break","Column Break","Fold","HTML","Button","Table","Table MultiSelect"):
			continue
		out[df.fieldname] = doc.get(df.fieldname)
	return out

def _filtered_values_for_customer(values: dict) -> dict:
	meta = frappe.get_meta("Customer")
	allowed = set(df.fieldname for df in meta.fields if not df.hidden and df.fieldtype not in ("Section Break","Column Break","Fold","HTML","Button","Table","Table MultiSelect"))
	safe = {}
	for k,v in (values or {}).items():
		if k in allowed:
			safe[k] = v
	return safe

@frappe.whitelist(allow_guest=False)
def create_customer(values: dict | None = None):
	if not _doctype_exists("Customer"):
		frappe.throw("ERPNext Customer doctype not found.")
	values = frappe.parse_json(values) if isinstance(values, str) else (values or {})
	safe = _filtered_values_for_customer(values)
	if not safe.get("customer_name"):
		frappe.throw("customer_name is required.")
	doc = frappe.get_doc({"doctype": "Customer", **safe})
	doc.insert(ignore_permissions=1)
	frappe.db.commit()
	return {"name": doc.name}

@frappe.whitelist(allow_guest=False)
def update_customer(name: str, values: dict | None = None):
	if not _doctype_exists("Customer"):
		frappe.throw("ERPNext Customer doctype not found.")
	if not frappe.db.exists("Customer", name):
		frappe.throw("Customer not found.")
	values = frappe.parse_json(values) if isinstance(values, str) else (values or {})
	safe = _filtered_values_for_customer(values)
	doc = frappe.get_doc("Customer", name)
	for k,v in safe.items():
		doc.set(k, v)
	doc.save(ignore_permissions=1)
	frappe.db.commit()
	return {"name": doc.name}
