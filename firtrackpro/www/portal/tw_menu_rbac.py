import frappe

def get_context(context):
    # Pass real roles into Jinja (Jinja sandbox can't call frappe.get_roles)
    user = frappe.session.user or "Guest"
    try:
        context.user_roles = frappe.get_roles(user)
    except Exception:
        context.user_roles = []

    # (Optional) expose full name for headers, etc.
    try:
        context.full_name = frappe.utils.get_fullname(user)
    except Exception:
        context.full_name = user
