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
    doctypes = sorted({r["parent"] for r in frappe.get_all("DocPerm", fields=["parent"])})
    perms = frappe.get_all("DocPerm", fields=["parent","role","permlevel","read","write","create","delete","submit","cancel","print","email","export","share","if_owner"], order_by="parent asc, permlevel asc, role asc")
    context.doctypes = doctypes
    context.perms = perms
    return context
