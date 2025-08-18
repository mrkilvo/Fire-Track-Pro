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
    try:
        jobs = frappe.get_all("RQ Job", fields=["name","creation","status","job_name","queue","exc_info","ended_at","scheduled_at","started_at"], order_by="creation desc", limit_page_length=100)
    except Exception:
        jobs = []
    context.jobs = jobs
    return context
