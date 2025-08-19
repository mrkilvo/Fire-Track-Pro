import frappe

ALLOW_ROLES = {"Administrator", "System Manager", "Member"}


def ensure_allowed():
	u = frappe.session.user
	if u == "Guest":
		frappe.local.flags.redirect_location = "/login"
		raise frappe.Redirect
	roles = set(frappe.get_roles(u))
	if not roles.intersection(ALLOW_ROLES):
		frappe.throw("Not permitted")


def get_context(context):
	ensure_allowed()
	rows = frappe.get_all(
		"Email Queue",
		fields=["name", "creation", "status", "subject", "sender", "message_id", "retry", "error"],
		order_by="creation desc",
		limit_page_length=100,
	)
	recips = frappe.get_all(
		"Email Queue Recipient",
		fields=["parent", "recipient", "status"],
		filters={"parent": ["in", [r["name"] for r in rows]]},
	)
	idx = {}
	for r in recips:
		idx.setdefault(r["parent"], []).append(f'{r["recipient"]} ({r["status"]})')
	for r in rows:
		r["recipients"] = ", ".join(idx.get(r["name"], []))
	context.emails = rows
	return context
