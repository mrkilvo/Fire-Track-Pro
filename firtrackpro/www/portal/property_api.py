import frappe
from frappe.utils import formatdate, nowdate
import urllib.parse

DOC_PROPERTY  = "FT Property"
DOC_ASSET     = "FT Asset"
DOC_DEFECT    = "FT Defect"
DOC_ADDRESS   = "Address"
DOC_QUOTATION = "Quotation"
DOC_JOB       = "FT Job"  # optional

def _cols(doctype: str, wanted: list[str]) -> list[str]:
    """Return only columns that actually exist on the doctype."""
    exists = []
    for col in wanted:
        # support alias like "name as job_title"
        base = col.split(" as ")[0].strip()
        if base in ("name", "modified"):  # always present
            exists.append(col)
        else:
            # handle SQL functions like max(...), etc. Pass them through.
            if "(" in base and ")" in base:
                exists.append(col)
            elif frappe.db.has_column(doctype, base):
                exists.append(col)
    return exists or ["name"]

def _addr_dict_and_text(addr_name: str):
    if not addr_name or not frappe.db.exists(DOC_ADDRESS, addr_name):
        return {}, ""
    fields = _cols(DOC_ADDRESS, [
        "address_line1","address_line2","city","state","pincode","country","latitude","longitude"
    ])
    a = frappe.db.get_value(DOC_ADDRESS, addr_name, fields, as_dict=True) or {}
    txt = ", ".join([x for x in [
        a.get("address_line1"),
        a.get("address_line2"),
        a.get("city"),
        a.get("state"),
        a.get("pincode"),
        a.get("country"),
    ] if x])
    return a, txt

@frappe.whitelist()
def get_property(name: str):
    if not name:
        frappe.throw("Missing name")
    fields = _cols(DOC_PROPERTY, [
        "name","property_name","property_customer","property_address","property_notes",
        "property_lat","property_lng",
        "property_access_keysafe_code","property_access_gate_code",
        "property_access_alarm_panel","property_access_parking","modified"
    ])
    d = frappe.db.get_value(DOC_PROPERTY, name, fields, as_dict=True)
    if not d:
        frappe.throw("Not found")

    cust = {}
    if d.get("property_customer") and frappe.db.exists("Customer", d["property_customer"]):
        cust = frappe.db.get_value("Customer", d["property_customer"], ["name","customer_name"], as_dict=True) or {}

    addr, addr_txt = _addr_dict_and_text(d.get("property_address"))

    has_access = any([
        d.get("property_access_keysafe_code"),
        d.get("property_access_gate_code"),
        d.get("property_access_alarm_panel"),
        d.get("property_access_parking"),
    ])

    return {
        "name": d.get("name"),
        "property_name": d.get("property_name") or d.get("name"),
        "customer": cust,
        "address": addr,
        "address_text": addr_txt,
        "property_lat": d.get("property_lat"),
        "property_lng": d.get("property_lng"),
        "property_notes": d.get("property_notes") or "",
        "has_access": 1 if has_access else 0,
        "modified": d.get("modified"),
    }

@frappe.whitelist()
def reveal_access(property_name: str):
    if not property_name:
        frappe.throw("Missing property_name")
    fields = _cols(DOC_PROPERTY, [
        "property_access_keysafe_code","property_access_gate_code",
        "property_access_alarm_panel","property_access_parking"
    ])
    d = frappe.db.get_value(DOC_PROPERTY, property_name, fields, as_dict=True)
    if not d:
        frappe.throw("Not found")
    d["property_access_last_revealed_on"] = formatdate(nowdate(), "d MMM yyyy")
    d["property_access_last_revealed_by"] = frappe.session.user
    return d

@frappe.whitelist()
def get_assets(property_name: str):
    if not property_name or not frappe.db.table_exists(DOC_ASSET):
        return []
    wanted = [
        "name","asset_label","asset_name","asset_type","asset_zone","asset_status",
        "asset_last_tested","asset_next_due","modified"
    ]
    fields = _cols(DOC_ASSET, wanted)
    return frappe.get_all(
        DOC_ASSET,
        filters={"asset_property": property_name} if frappe.db.has_column(DOC_ASSET, "asset_property") else {"name": ["!=", ""]},
        fields=fields,
        order_by="modified desc",
        limit=500,
        ignore_permissions=1,
    )

@frappe.whitelist()
def get_history(property_name: str):
    if not property_name or not frappe.db.table_exists(DOC_JOB):
        return []
    wanted = ["name as job_title","job_status","job_required_date","job_scheduled_start","modified"]
    fields = _cols(DOC_JOB, wanted)
    return frappe.get_all(
        DOC_JOB,
        filters={"job_property": property_name} if frappe.db.has_column(DOC_JOB, "job_property") else {"name": ["!=", ""]},
        fields=fields,
        order_by="modified desc",
        limit=200,
        ignore_permissions=1,
    )

@frappe.whitelist()
def get_quotes(property_name: str):
    if not property_name or not frappe.db.table_exists(DOC_QUOTATION):
        return []
    wanted = ["name","customer_name","transaction_date","valid_till","grand_total","status","modified"]
    fields = _cols(DOC_QUOTATION, wanted)

    if frappe.db.has_column(DOC_QUOTATION, "quote_property"):
        filters = {"quote_property": property_name}
    else:
        cust = frappe.db.get_value(DOC_PROPERTY, property_name, "property_customer") or ""
        if not cust:
            return []
        filters = {"customer_name": ["like", f"%{cust}%"]}

    return frappe.get_all(
        DOC_QUOTATION,
        filters=filters,
        fields=fields,
        order_by="modified desc",
        limit=200,
        ignore_permissions=1,
    )

@frappe.whitelist()
def get_defects(property_name: str):
    if not property_name or not frappe.db.table_exists(DOC_DEFECT):
        return []
    wanted = ["name","defect_severity","defect_status","defect_description","defect_quotation","modified"]
    fields = _cols(DOC_DEFECT, wanted)
    filters = {"defect_property": property_name} if frappe.db.has_column(DOC_DEFECT, "defect_property") else {"name": ["!=", ""]}
    return frappe.get_all(
        DOC_DEFECT,
        filters=filters,
        fields=fields,
        order_by="modified desc",
        limit=500,
        ignore_permissions=1,
    )
@frappe.whitelist()
def get_property_details(name: str):
    """
    Returns:
      {
        "doc": { ... all FT Property fields ... },
        "meta": { "fields": [{fieldname,label,fieldtype,idx}, ...] },
        "links": {
            "desk_property": "/app/ft-property/<name>",
            "customer": {"name": "...", "label": "...", "desk": "/app/customer/<name>"},
            "address":  {"name": "...", "label": "...", "desk": "/app/address/<name>"},
            "access":   {"name": "...", "label": "...", "desk": "/app/ft-property-access/<name>"},
            "related": {
                "assets":  {"count": N, "desk": "/app/ft-asset?asset_property=<name>"},
                "defects": {"count": N, "desk": "/app/ft-defect?defect_property=<name>"},
                "jobs":    {"count": N, "desk": "/app/ft-job?job_property=<name>"},
                "quotes":  {"count": M, "desk": "/app/quotation?quote_property=<name>"}
            }
        }
      }
    """
    if not name:
        frappe.throw("Missing name")

    # FT Property doc (all fields)
    if not frappe.db.exists(DOC_PROPERTY, name):
        frappe.throw("Property not found")

    prop = frappe.get_doc(DOC_PROPERTY, name)  # object with all fields/children
    doc = prop.as_dict(no_nulls=True)

    # Minimal meta so frontend can label fields nicely
    meta = frappe.get_meta(DOC_PROPERTY)
    meta_fields = [
        {"fieldname": df.fieldname, "label": df.label, "fieldtype": df.fieldtype, "idx": df.idx}
        for df in meta.fields
    ]

    # Associated primary links
    cust_name = doc.get("property_customer")
    addr_name = doc.get("property_address")
    acc_name  = doc.get("property_access") if frappe.db.has_column(DOC_PROPERTY, "property_access") else None

    customer = {}
    if cust_name and frappe.db.exists("Customer", cust_name):
        customer = {
            "name": cust_name,
            "label": frappe.db.get_value("Customer", cust_name, "customer_name") or cust_name,
            "desk": f"/app/Customer/{urllib.parse.quote(cust_name)}",
        }

    address = {}
    if addr_name and frappe.db.exists("Address", addr_name):
        atitle = frappe.db.get_value("Address", addr_name, "address_title") or addr_name
        address = {
            "name": addr_name,
            "label": atitle,
            "desk": f"/app/Address/{urllib.parse.quote(addr_name)}",
        }

    access = {}
    if acc_name and frappe.db.exists("FT Property Access", acc_name):
        access = {
            "name": acc_name,
            "label": acc_name,
            "desk": f"/app/FT%20Property%20Access/{urllib.parse.quote(acc_name)}",
        }

    # Related: counts & desk list views (filtering by link fields when present)
    def _count(doctype, link_field, value):
        if not frappe.db.table_exists(doctype):
            return 0
        if not frappe.db.has_column(doctype, link_field):
            return 0
        return frappe.db.count(doctype, {link_field: value})

    links = {
        "desk_property": f"/app/FT%20Property/{urllib.parse.quote(name)}",
        "customer": customer or None,
        "address": address or None,
        "access": access or None,
        "related": {
            "assets": {
                "count": _count(DOC_ASSET, "asset_property", name),
                "desk": f"/app/FT%20Asset?asset_property={urllib.parse.quote(name)}",
            },
            "defects": {
                "count": _count(DOC_DEFECT, "defect_property", name),
                "desk": f"/app/FT%20Defect?defect_property={urllib.parse.quote(name)}",
            },
            "jobs": {
                "count": _count("FT Job", "job_property", name) if frappe.db.table_exists("FT Job") else 0,
                "desk": f"/app/FT%20Job?job_property={urllib.parse.quote(name)}",
            },
            "quotes": {
                # Prefer dedicated link field, fallback to customer filter in desk
                "count": _count(DOC_QUOTATION, "quote_property", name) if frappe.db.has_column(DOC_QUOTATION, "quote_property") else 0,
                "desk": f"/app/Quotation?quote_property={urllib.parse.quote(name)}"
                        if frappe.db.has_column(DOC_QUOTATION, "quote_property")
                        else f"/app/Quotation?customer={urllib.parse.quote(customer.get('name'))}" if customer else "/app/Quotation",
            },
        },
    }

    return {"doc": doc, "meta": {"fields": meta_fields}, "links": links}