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
    context.csrf_token = frappe.sessions.get_csrf_token()
    return context
