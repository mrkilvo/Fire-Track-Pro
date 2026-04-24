import json

import frappe
from frappe import _

# -----------------------------
# Helpers
# -----------------------------


def _json_or_form():
	j = None
	try:
		j = frappe.request.get_json(silent=True)
	except Exception:
		j = None
	if isinstance(j, dict):
		return j
	return dict(frappe.form_dict or {})


def _coerce_bool(v):
	if isinstance(v, bool):
		return int(v)
	if v is None:
		return 0
	return 1 if str(v).lower() in ("1", "true", "yes", "y") else 0


def _select_options_from_meta(doctype: str, fieldname: str) -> list[str]:
	df = frappe.get_meta(doctype).get_field(fieldname)
	if not df or df.fieldtype != "Select":
		return []
	return [o.strip() for o in (df.options or "").split("\n") if o.strip()]


def _has_field(doctype: str, fieldname: str) -> bool:
	try:
		return bool(frappe.get_meta(doctype).get_field(fieldname))
	except Exception:
		return False


def _doctype_exists(doctype: str) -> bool:
	try:
		return bool(frappe.db.exists("DocType", doctype))
	except Exception:
		return False


def _safe_supplier_fields() -> list[str]:
	base_candidates = [
		"name",
		"supplier_name",
		"supplier_group",
		"supplier_type",
		"disabled",
		"modified",
		"website",
		"tax_id",
		"default_currency",
		"email_id",
		"mobile_no",
		"suppliers_status",
	]
	fields = []
	for f in base_candidates:
		if f in ("name", "modified"):
			fields.append(f)
			continue
		if _has_field("Supplier", f):
			fields.append(f)
	return fields


def _normalize_row(row: dict) -> dict:
	out = dict(row or {})
	for k in (
		"supplier_name",
		"supplier_group",
		"supplier_type",
		"website",
		"tax_id",
		"default_currency",
		"email_id",
		"mobile_no",
		"suppliers_status",
	):
		out.setdefault(k, "")
	out.setdefault("disabled", 0)
	return out


def _doc_to_safe_dict(doc: "frappe.model.document.Document") -> dict:
	as_json = frappe.as_json(doc, indent=None)
	data = json.loads(as_json)
	return data


def _field_meta(doctype: str) -> list[dict]:
	meta = frappe.get_meta(doctype)
	out = []
	for df in meta.fields:
		out.append(
			{
				"label": df.label,
				"fieldname": df.fieldname,
				"fieldtype": df.fieldtype,
				"options": df.options,
				"in_list_view": df.in_list_view,
				"reqd": df.reqd,
				"hidden": df.hidden,
				"depends_on": df.depends_on,
				"collapsible": df.collapsible,
				"collapsible_depends_on": df.collapsible_depends_on,
				"column": df.columns or 0,
			}
		)
	return out


# -----------------------------
# Supplier List / CRUD
# -----------------------------


@frappe.whitelist()
def list_suppliers(search=None, start=0, limit=50, ignore_permissions: int = 1):
	try:
		start = int(start or 0)
		limit = min(int(limit or 50), 200)
		filters = []
		if search:
			filters.append(["Supplier", "supplier_name", "like", f"%{search}%"])

		fields = _safe_supplier_fields()
		kw = dict(
			doctype="Supplier",
			filters=filters,
			fields=fields,
			order_by="modified desc",
			start=start,
			page_length=limit,
		)
		if int(ignore_permissions or 0):
			kw["ignore_permissions"] = True

		data = frappe.get_list(**kw)
		data = [_normalize_row(d) for d in data]
		total = frappe.db.count("Supplier", filters=filters)
		return {"data": data, "total": total, "start": start, "limit": limit}
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Suppliers API: list_suppliers")
		raise


@frappe.whitelist()
def get_supplier(name: str, ignore_permissions: int = 1):
	if not name:
		frappe.throw(_("Missing supplier name"))
	try:
		doc = frappe.get_doc("Supplier", name)
		if not int(ignore_permissions or 0):
			doc.check_permission("read")
		return _normalize_row(
			{
				"name": doc.name,
				"supplier_name": getattr(doc, "supplier_name", ""),
				"supplier_group": getattr(doc, "supplier_group", ""),
				"supplier_type": getattr(doc, "supplier_type", ""),
				"tax_id": getattr(doc, "tax_id", ""),
				"website": getattr(doc, "website", ""),
				"email_id": getattr(doc, "email_id", ""),
				"mobile_no": getattr(doc, "mobile_no", ""),
				"default_currency": getattr(doc, "default_currency", ""),
				"disabled": int(getattr(doc, "disabled", 0)),
				"suppliers_status": getattr(doc, "suppliers_status", ""),
			}
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Suppliers API: get_supplier")
		raise


@frappe.whitelist()
def upsert_supplier(payload: dict | None = None, ignore_permissions: int = 0):
	data = payload or _json_or_form()
	if not data.get("supplier_name"):
		frappe.throw(_("supplier_name is required"))
	try:
		name = data.get("name")
		if name:
			doc = frappe.get_doc("Supplier", name)
			if not int(ignore_permissions or 0):
				doc.check_permission("write")
		else:
			doc = frappe.new_doc("Supplier")

		doc.supplier_name = data.get("supplier_name")
		if data.get("supplier_group"):
			doc.supplier_group = data.get("supplier_group")
		if data.get("supplier_type"):
			doc.supplier_type = data.get("supplier_type")
		if "disabled" in data:
			doc.disabled = _coerce_bool(data.get("disabled"))

		for k in ("tax_id", "website", "default_currency"):
			if k in data and data.get(k) is not None:
				setattr(doc, k, data.get(k))

		for k in ("email_id", "mobile_no", "suppliers_status"):
			if k in data and data.get(k) is not None and _has_field("Supplier", k):
				setattr(doc, k, data.get(k))

		doc.save(ignore_permissions=bool(int(ignore_permissions or 0)))
		frappe.db.commit()
		return {"name": doc.name}
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Suppliers API: upsert_supplier")
		raise


@frappe.whitelist()
def delete_supplier(name: str, ignore_permissions: int = 0):
	if not name:
		frappe.throw(_("Missing supplier name"))
	try:
		frappe.delete_doc("Supplier", name, ignore_permissions=bool(int(ignore_permissions or 0)))
		frappe.db.commit()
		return {"ok": True}
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Suppliers API: delete_supplier")
		raise


@frappe.whitelist()
def options():
	try:
		supplier_meta = frappe.get_meta("Supplier")
		select_supplier_type = _select_options_from_meta("Supplier", "supplier_type") or [
			"Company",
			"Individual",
		]
		select_suppliers_status = (
			_select_options_from_meta("Supplier", "suppliers_status")
			if _has_field("Supplier", "suppliers_status")
			else ["New", "Preferred", "Suspended"]
		)
		link_supplier_groups = frappe.get_all("Supplier Group", pluck="name", order_by="name asc")
		link_currencies = frappe.get_all("Currency", pluck="name", order_by="name asc")

		return {
			"select": {
				"supplier_type": select_supplier_type,
				"suppliers_status": select_suppliers_status,
			},
			"link": {
				"supplier_group": link_supplier_groups,
				"currency": link_currencies,
			},
			"has": {
				"email_id": bool(supplier_meta.get_field("email_id")),
				"mobile_no": bool(supplier_meta.get_field("mobile_no")),
				"suppliers_status": bool(supplier_meta.get_field("suppliers_status")),
			},
		}
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Suppliers API: options")
		raise


@frappe.whitelist()
def link_lookup(doctype: str, search: str | None = None, limit: int = 20):
	if not doctype:
		frappe.throw(_("doctype is required"))
	try:
		limit = min(int(limit or 20), 100)
		filters = []
		if search:
			filters.append(["name", "like", f"%{search}%"])
		names = frappe.get_list(
			doctype, filters=filters, pluck="name", page_length=limit, order_by="name asc"
		)
		return {"results": names}
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Suppliers API: link_lookup")
		raise


# -----------------------------
# Full doc + History
# -----------------------------


@frappe.whitelist()
def get_supplier_full(name: str, ignore_permissions: int = 1):
	if not name:
		frappe.throw(_("Missing supplier name"))
	try:
		doc = frappe.get_doc("Supplier", name)
		if not int(ignore_permissions or 0):
			doc.check_permission("read")
		payload = {
			"doc": _doc_to_safe_dict(doc),
			"meta": _field_meta("Supplier"),
		}
		return payload
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Suppliers API: get_supplier_full")
		raise


@frappe.whitelist()
def supplier_history(name: str, limit: int = 20, ignore_permissions: int = 1):
	if not name:
		frappe.throw(_("Missing supplier name"))
	try:
		versions = frappe.get_all(
			"Version",
			filters=dict(ref_doctype="Supplier", docname=name),
			fields=["name", "owner", "creation", "data"],
			order_by="creation desc",
			page_length=min(int(limit or 20), 100),
			ignore_permissions=bool(int(ignore_permissions or 0)),
		)
		parsed_versions = []
		for v in versions:
			summary = []
			try:
				data = json.loads(v.get("data") or "{}")
				changes = data.get("changed", []) or []
				for ch in changes:
					if isinstance(ch, list) and len(ch) >= 3:
						fn, old, new = ch[0], ch[1], ch[2]
						summary.append({"fieldname": fn, "old": old, "new": new})
			except Exception:
				pass
			parsed_versions.append(
				{"name": v.get("name"), "by": v.get("owner"), "when": v.get("creation"), "changes": summary}
			)

		comments = frappe.get_all(
			"Comment",
			filters=dict(reference_doctype="Supplier", reference_name=name),
			fields=["name", "content", "comment_type", "creation", "owner"],
			order_by="creation desc",
			page_length=min(int(limit or 20), 100),
			ignore_permissions=bool(int(ignore_permissions or 0)),
		)

		return {"versions": parsed_versions, "comments": comments}
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Suppliers API: supplier_history")
		raise


# -----------------------------
# Financials (portal summary)
# -----------------------------


@frappe.whitelist()
def supplier_financials(name: str, ignore_permissions: int = 1):
	"""
	Returns portal-friendly financial aggregates for a Supplier:
	  - totals: purchase_orders_total, invoices_total, invoices_outstanding, payments_total
	  - counts/status splits
	  - recent: last 5 POs, last 5 Invoices, last 5 Payments

	Works even if some doctypes aren't installed; missing parts return zeros/empty lists.
	"""
	if not name:
		frappe.throw(_("Missing supplier name"))

	res = {
		"totals": {
			"purchase_orders_total": 0.0,
			"invoices_total": 0.0,
			"invoices_outstanding": 0.0,
			"payments_total": 0.0,
		},
		"counts": {
			"po": {"total": 0, "to_receive": 0, "to_bill": 0, "completed": 0},
			"pi": {"total": 0, "draft": 0, "submitted": 0, "paid": 0, "overdue": 0},
		},
		"recent": {
			"purchase_orders": [],
			"purchase_invoices": [],
			"payments": [],
		},
	}

	try:
		# Purchase Orders
		if _doctype_exists("Purchase Order"):
			# Sum grand total (prefer base_grand_total if present)
			po_fields = (
				"sum(base_grand_total) as total"
				if _has_field("Purchase Order", "base_grand_total")
				else "sum(grand_total) as total"
			)
			rows = frappe.get_all(
				"Purchase Order",
				filters={"supplier": name, "docstatus": 1},
				fields=[po_fields, "count(name) as cnt"],
				ignore_permissions=bool(int(ignore_permissions or 0)),
			)
			if rows:
				res["totals"]["purchase_orders_total"] = float(rows[0].get("total") or 0)
				res["counts"]["po"]["total"] = int(rows[0].get("cnt") or 0)

			# Status splits
			for status_key, status_val in [
				("completed", "Completed"),
				("to_receive", "To Receive"),
				("to_bill", "To Bill"),
			]:
				cnt = frappe.db.count(
					"Purchase Order",
					filters={"supplier": name, "docstatus": 1, "status": status_val},
				)
				res["counts"]["po"][status_key] = int(cnt or 0)

			# Recent POs
			rec = frappe.get_all(
				"Purchase Order",
				filters={"supplier": name, "docstatus": 1},
				fields=["name", "transaction_date", "status", "grand_total", "base_grand_total", "currency"],
				order_by="modified desc",
				page_length=5,
				ignore_permissions=bool(int(ignore_permissions or 0)),
			)
			# Normalize amount column
			for r in rec:
				r["amount"] = r.get("base_grand_total", None) or r.get("grand_total", 0)
			res["recent"]["purchase_orders"] = rec

		# Purchase Invoices
		if _doctype_exists("Purchase Invoice"):
			# Totals
			inv_fields_total = (
				"sum(base_grand_total) as total"
				if _has_field("Purchase Invoice", "base_grand_total")
				else "sum(grand_total) as total"
			)
			inv_fields_out = (
				"sum(outstanding_amount) as outamt"
				if _has_field("Purchase Invoice", "outstanding_amount")
				else None
			)

			fields_list = [inv_fields_total]
			if inv_fields_out:
				fields_list.append(inv_fields_out)
			fields_list.append("count(name) as cnt")

			rows = frappe.get_all(
				"Purchase Invoice",
				filters={"supplier": name, "docstatus": 1},
				fields=fields_list,
				ignore_permissions=bool(int(ignore_permissions or 0)),
			)
			if rows:
				res["totals"]["invoices_total"] = float(rows[0].get("total") or 0)
				res["totals"]["invoices_outstanding"] = float(rows[0].get("outamt") or 0)
				res["counts"]["pi"]["total"] = int(rows[0].get("cnt") or 0)

			# Status splits
			for status_key, status_val in [
				("draft", "Draft"),
				("submitted", "Unpaid"),
				("paid", "Paid"),
				("overdue", "Overdue"),
			]:
				cnt = frappe.db.count(
					"Purchase Invoice",
					filters={"supplier": name, "status": status_val},
				)
				res["counts"]["pi"][status_key] = int(cnt or 0)

			# Recent Invoices
			rec = frappe.get_all(
				"Purchase Invoice",
				filters={"supplier": name},
				fields=[
					"name",
					"posting_date",
					"status",
					"grand_total",
					"base_grand_total",
					"outstanding_amount",
					"currency",
					"docstatus",
				],
				order_by="modified desc",
				page_length=5,
				ignore_permissions=bool(int(ignore_permissions or 0)),
			)
			for r in rec:
				r["amount"] = r.get("base_grand_total", None) or r.get("grand_total", 0)
			res["recent"]["purchase_invoices"] = rec

		# Payments (Payment Entry)
		if _doctype_exists("Payment Entry"):
			pay_fields = "sum(paid_amount) as total" if _has_field("Payment Entry", "paid_amount") else None
			if pay_fields:
				rows = frappe.get_all(
					"Payment Entry",
					filters={"party_type": "Supplier", "party": name, "docstatus": 1, "payment_type": "Pay"},
					fields=[pay_fields],
					ignore_permissions=bool(int(ignore_permissions or 0)),
				)
				if rows:
					res["totals"]["payments_total"] = float(rows[0].get("total") or 0)

			rec = frappe.get_all(
				"Payment Entry",
				filters={"party_type": "Supplier", "party": name},
				fields=["name", "posting_date", "paid_amount", "mode_of_payment", "docstatus", "status"],
				order_by="modified desc",
				page_length=5,
				ignore_permissions=bool(int(ignore_permissions or 0)),
			)
			res["recent"]["payments"] = rec

	except Exception:
		frappe.log_error(frappe.get_traceback(), "Suppliers API: supplier_financials")
		raise

	return res
