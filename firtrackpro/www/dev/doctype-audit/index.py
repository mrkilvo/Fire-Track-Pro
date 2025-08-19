import re

import frappe

ALLOW_ROLES = {"Administrator", "System Manager", "Member"}
META_IGNORE = {
	"name",
	"owner",
	"creation",
	"modified",
	"modified_by",
	"idx",
	"docstatus",
	"parent",
	"parentfield",
	"parenttype",
	"amended_from",
	"naming_series",
}


def ensure_allowed():
	u = frappe.session.user
	if u == "Guest":
		frappe.local.flags.redirect_location = "/login"
		raise frappe.Redirect
	roles = set(frappe.get_roles(u))
	if not roles.intersection(ALLOW_ROLES):
		frappe.throw("Not permitted")


def norm_prefix(dt):
	s = re.sub(r"[^a-z0-9]+", "_", dt.lower()).strip("_")
	return s


def app_doctypes():
	q1 = frappe.get_all("DocType", filters={"custom": 1}, fields=["name"])
	q2 = frappe.get_all("DocType", filters=[["module", "like", "Firtrackpro%"]], fields=["name"])
	names = sorted({r["name"] for r in q1 + q2})
	return names


def audit_doctype(dt):
	bad_fields = []
	bad_links = []
	prefix = norm_prefix(dt) + "_"
	fields = frappe.get_all(
		"DocField", filters={"parent": dt}, fields=["fieldname", "fieldtype", "options", "label"]
	)
	for f in fields:
		fn = f["fieldname"] or ""
		ft = f["fieldtype"] or ""
		op = f["options"] or ""
		if fn and fn not in META_IGNORE and not fn.startswith(prefix):
			bad_fields.append({"fieldname": fn, "label": f.get("label"), "reason": "prefix"})
		if ft in ("Link", "Table") and op:
			try:
				if not frappe.db.exists("DocType", op):
					bad_links.append({"fieldname": fn, "label": f.get("label"), "target": op})
			except Exception:
				bad_links.append({"fieldname": fn, "label": f.get("label"), "target": op})
	return {"doctype": dt, "bad_fields": bad_fields, "bad_links": bad_links}


def get_context(context):
	ensure_allowed()
	dts = app_doctypes()
	audits = [audit_doctype(dt) for dt in dts]
	audits = [a for a in audits if a["bad_fields"] or a["bad_links"]]
	audits.sort(key=lambda x: x["doctype"])
	context.audits = audits
	context.total = len(dts)
	context.issues = sum(len(a["bad_fields"]) + len(a["bad_links"]) for a in audits)
	return context
