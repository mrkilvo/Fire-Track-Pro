import frappe

ALLOWED_ROLES = {
	"Administrator",
	"System Manager",
	"Member",
	"Accounts User",
	"Purchase User",
	"Purchase Manager",
}


def _ensure_portal_access():
	user = frappe.session.user
	if user == "Guest":
		raise frappe.PermissionError("Login required")
	if set(frappe.get_roles(user)).isdisjoint(ALLOWED_ROLES):
		raise frappe.PermissionError("Not permitted")


def _safe_doctype_exists(dt):
	try:
		frappe.get_meta(dt)
		return True
	except Exception:
		return False


def _clean_date(v):
	if not v:
		return None
	v = str(v).strip()[:10]
	return v if len(v) == 10 and v[4] == "-" and v[7] == "-" else None


@frappe.whitelist()
def list_purchase_orders(
	q=None, status="all", date_from=None, date_to=None, limit_start=0, limit=50, supplier=None
):
	_ensure_portal_access()
	if not _safe_doctype_exists("Purchase Order"):
		return {"items": [], "total": 0}

	status = (status or "all").strip()
	date_from = _clean_date(date_from)
	date_to = _clean_date(date_to)
	try:
		limit_start = int(limit_start or 0)
		limit = max(1, min(int(limit or 50), 200))
	except Exception:
		limit_start, limit = 0, 50

	filters, or_filters = {}, []
	if status.lower() != "all":
		filters["status"] = status
	if date_from and date_to:
		filters["transaction_date"] = ["between", [date_from, date_to]]
	elif date_from:
		filters["transaction_date"] = [">=", date_from]
	elif date_to:
		filters["transaction_date"] = ["<=", date_to]
	if supplier:
		filters["supplier"] = supplier
	if q:
		like = f"%{q}%"
		or_filters = [
			["Purchase Order", "name", "like", like],
			["Purchase Order", "supplier_name", "like", like],
			["Purchase Order", "supplier", "like", like],
		]

	fields = [
		"name",
		"transaction_date",
		"supplier",
		"supplier_name",
		"status",
		"schedule_date",
		"grand_total",
		"currency",
		"docstatus",
	]

	try:
		rows = frappe.get_all(
			"Purchase Order",
			filters=filters,
			or_filters=or_filters,
			fields=fields,
			order_by="transaction_date desc, creation desc",
			limit_start=limit_start,
			limit=limit,
			ignore_permissions=1,
		)
	except Exception:
		rows = frappe.get_all(
			"Purchase Order",
			filters=filters,
			fields=fields,
			order_by="transaction_date desc, creation desc",
			limit_start=limit_start,
			limit=limit,
			ignore_permissions=1,
		)

	items = [
		{
			"name": r.name,
			"transaction_date": r.transaction_date,
			"supplier": r.supplier,
			"supplier_name": r.supplier_name,
			"status": r.status,
			"schedule_date": r.schedule_date,
			"grand_total": float(r.grand_total or 0),
			"currency": r.currency or "AUD",
			"docstatus": r.docstatus,
		}
		for r in rows
	]

	try:
		if or_filters:
			total = len(
				frappe.get_all(
					"Purchase Order",
					filters=filters,
					or_filters=or_filters,
					fields=["name"],
					limit=10000,
					ignore_permissions=1,
				)
			)
		else:
			total = frappe.db.count("Purchase Order", filters=filters)
	except Exception:
		total = limit_start + len(items)

	return {"items": items, "total": total}


@frappe.whitelist()
def get_purchase_order(name):
	_ensure_portal_access()
	if not _safe_doctype_exists("Purchase Order"):
		return {}
	try:
		d = frappe.get_doc("Purchase Order", name)
	except Exception:
		return {}
	return {
		"name": d.name,
		"transaction_date": d.transaction_date,
		"supplier": d.supplier,
		"supplier_name": d.supplier_name,
		"status": d.status,
		"schedule_date": d.schedule_date,
		"grand_total": float(getattr(d, "grand_total", 0) or 0),
		"currency": getattr(d, "currency", "AUD") or "AUD",
		"docstatus": getattr(d, "docstatus", 0),
	}
