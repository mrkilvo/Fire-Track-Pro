import frappe


def _addr_fmt(a):
    if not a:
        return ""
    parts = [
        a.get("address_line1"),
        a.get("address_line2"),
        a.get("city"),
        a.get("state"),
        a.get("pincode"),
        a.get("country"),
    ]
    parts = [p for p in parts if p]
    return ", ".join(parts)


def _count(doctype, filters=None):
    rows = frappe.db.get_list(
        doctype, filters=filters or {}, fields=["count(name) as _total"], limit=1
    )
    return int((rows[0]["_total"] if rows else 0) or 0)


def _row_from_property_row(row):
    # customer label
    cust_name = ""
    if row.get("property_customer"):
        res = frappe.get_all(
            "Customer",
            filters={"name": row["property_customer"]},
            fields=["customer_name"],
            limit=1,
        )
        if res:
            cust_name = res[0].get("customer_name") or row["property_customer"]

    # address
    addr_text, state = "", ""
    if row.get("property_address"):
        a = frappe.get_all(
            "Address",
            filters={"name": row["property_address"]},
            fields=[
                "address_line1",
                "address_line2",
                "city",
                "state",
                "pincode",
                "country",
            ],
            limit=1,
        )
        if a:
            a = a[0]
            state = (a.get("state") or "").upper()
            addr_text = _addr_fmt(a)

    # next service (from rule next occurrence if present)
    next_service = "—"
    sr = frappe.get_all(
        "FT Schedule Rule",
        filters={"schedule_rule_property": row["name"]},
        fields=["schedule_rule_next_occurrence"],
        order_by="schedule_rule_next_occurrence asc",
        limit=1,
    )
    if sr and sr[0].get("schedule_rule_next_occurrence"):
        next_service = str(sr[0]["schedule_rule_next_occurrence"])[:10]

    # open defects
    open_defects = _count(
        "FT Defect",
        {
            "defect_property": row["name"],
            "defect_status": [
                "in",
                ["Open", "Quoted", "Approved", "In Progress", "Deferred"],
            ],
        },
    )

    return {
        "name": row["name"],
        "property_name": row.get("property_name") or row["name"],
        "client_name": cust_name or "—",
        "address": addr_text or "—",
        "status": "Active",
        "next_service": next_service,
        "open_defects": open_defects,
        "region": state or "",
    }


def get_context(context):
    rows = frappe.get_all(
        "FT Property",
        fields=[
            "name",
            "property_name",
            "property_customer",
            "property_address",
            "property_lat",
            "property_lng",
        ],
        order_by="modified desc",
        limit_page_length=1000,
    )
    context.properties = [_row_from_property_row(r) for r in rows]
    # expose CSRF token in context for convenience (Jinja variable)
    try:
        context.csrf_token = frappe.sessions.get_csrf_token()
    except Exception:
        context.csrf_token = ""
    return context
