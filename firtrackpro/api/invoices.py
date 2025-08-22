import frappe
from frappe.utils import strip_html

def _ensure_portal_access():
    user = frappe.session.user
    if user == "Guest":
        raise frappe.PermissionError("Login required")
    # Keep your elevated portal guard; include Member per your policy
    roles = set(frappe.get_roles(user))
    if roles.isdisjoint({"Administrator", "System Manager", "Member", "Accounts User"}):
        raise frappe.PermissionError("Not permitted")

def _safe_sales_invoice_exists():
    try:
        frappe.get_meta("Sales Invoice")
        return True
    except Exception:
        return False

def _clean_date(v):
    if not v:
        return None
    v = str(v).strip()[:10]
    # very basic YYYY-MM-DD allowlist
    return v if len(v) == 10 and v[4] == "-" and v[7] == "-" else None

@frappe.whitelist()
def list_invoices(q=None, status="all", date_from=None, date_to=None, limit_start=0, limit=50, customer=None):
    _ensure_portal_access()

    # Short-circuit if SI is unavailable (ERPNext not installed or DocType missing)
    if not _safe_sales_invoice_exists():
        return {"items": [], "total": 0}

    # Sanitize inputs
    status = (status or "all").strip()
    date_from = _clean_date(date_from)
    date_to = _clean_date(date_to)
    try:
        limit_start = int(limit_start or 0)
        limit = max(1, min(int(limit or 50), 200))
    except Exception:
        limit_start, limit = 0, 50

    filters = {}
    or_filters = []
    if status.lower() != "all":
        filters["status"] = status
    if date_from and date_to:
        filters["posting_date"] = ["between", [date_from, date_to]]
    elif date_from:
        filters["posting_date"] = [">=", date_from]
    elif date_to:
        filters["posting_date"] = ["<=", date_to]
    if customer:
        filters["customer"] = customer
    if q:
        like = f"%{q}%"
        or_filters = [
            ["Sales Invoice", "name", "like", like],
            ["Sales Invoice", "customer_name", "like", like],
            ["Sales Invoice", "remarks", "like", like],
        ]

    fields = [
        "name",
        "posting_date",
        "customer",
        "customer_name",
        "status",
        "due_date",
        "grand_total",
        "outstanding_amount",
        "currency",
        "docstatus",
    ]

    # Fetch rows (never raise; fall back to safer query if needed)
    rows = []
    try:
        rows = frappe.get_all(
            "Sales Invoice",
            filters=filters,
            or_filters=or_filters,
            fields=fields,
            order_by="posting_date desc, creation desc",
            limit_start=limit_start,
            limit=limit,
            ignore_permissions=1,
        )
    except Exception:
        # Fallback without or_filters if DB complains
        rows = frappe.get_all(
            "Sales Invoice",
            filters=filters,
            fields=fields,
            order_by="posting_date desc, creation desc",
            limit_start=limit_start,
            limit=limit,
            ignore_permissions=1,
        )

    items = []
    for r in rows:
        items.append({
            "name": r.name,
            "posting_date": r.posting_date,
            "customer": r.customer,
            "customer_name": r.customer_name,
            "status": r.status,
            "due_date": r.due_date,
            "grand_total": float(r.grand_total or 0),
            "outstanding_amount": float(r.outstanding_amount or 0),
            "currency": r.currency or "AUD",
            "docstatus": r.docstatus,
        })

    # Compute total defensively. Prefer exact count; otherwise provide a safe lower bound.
    total = 0
    try:
        if or_filters:
            # Counting with or_filters can be heavy; cap to 10k for safety
            total = len(frappe.get_all(
                "Sales Invoice",
                filters=filters,
                or_filters=or_filters,
                fields=["name"],
                limit_start=0,
                limit=10000,
                ignore_permissions=1,
            ))
        else:
            total = frappe.db.count("Sales Invoice", filters=filters)
    except Exception:
        total = limit_start + len(items)

    return {"items": items, "total": total}

@frappe.whitelist()
def get_invoice(name):
    _ensure_portal_access()
    if not _safe_sales_invoice_exists():
        return {}
    try:
        doc = frappe.get_doc("Sales Invoice", name)
    except Exception:
        return {}
    return {
        "name": doc.name,
        "posting_date": doc.posting_date,
        "customer": doc.customer,
        "customer_name": doc.customer_name,
        "status": doc.status,
        "due_date": doc.due_date,
        "grand_total": float(getattr(doc, "grand_total", 0) or 0),
        "outstanding_amount": float(getattr(doc, "outstanding_amount", 0) or 0),
        "currency": getattr(doc, "currency", "AUD") or "AUD",
        "remarks": getattr(doc, "remarks", None),
        "docstatus": getattr(doc, "docstatus", 0),
    }
