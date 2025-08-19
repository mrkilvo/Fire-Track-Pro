import frappe

@frappe.whitelist(allow_guest=False)
def get_user_roles():
    user = frappe.session.user
    full_name = frappe.db.get_value("User", user, "full_name") or user
    try:
        roles = frappe.get_roles(user) or []
    except Exception:
        rows = frappe.get_all(
            "Has Role",
            filters={"parenttype": "User", "parent": user},
            fields=["role"],
            limit=500,
        )
        roles = [r["role"] for r in rows]

    if user == "Administrator" and "System Manager" not in roles:
        roles.append("System Manager")
    roles.append("Authenticated")
    return {"user": user, "full_name": full_name, "roles": sorted(set(roles))}
