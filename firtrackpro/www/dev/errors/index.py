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
	logs = frappe.get_all(
		"Error Log",
		fields=["name", "creation", "method", "error"],
		order_by="creation desc",
		limit_page_length=50,
	)
	context.logs = logs
	return context
