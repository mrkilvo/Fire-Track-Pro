import frappe
from frappe.utils import strip_html

def _ensure_portal_access():
    user = frappe.session.user
    if user == "Guest":
        raise frappe.PermissionError("Login required")
    roles = set(frappe.get_roles(user))
    if roles.isdisjoint({"Administrator", "System Manager", "Member"}):
        raise frappe.PermissionError("Not permitted")

@frappe.whitelist()
def get_email_accounts():
    _ensure_portal_access()
    fields = ["name", "email_id", "enable_incoming", "enable_outgoing", "default_outgoing"]
    accounts = frappe.get_all(
        "Email Account",
        filters={"enable_incoming": 1},
        fields=fields,
        order_by="name asc",
        ignore_permissions=1,
    )
    if not accounts:
        accounts = frappe.get_all(
            "Email Account",
            filters={"enable_outgoing": 1},
            fields=fields,
            order_by="name asc",
            ignore_permissions=1,
        )
    if not accounts:
        accounts = frappe.get_all(
            "Email Account",
            fields=fields,
            order_by="name asc",
            ignore_permissions=1,
        )
    return accounts

def _comm_filters(email_account, mailbox):
    f = {"communication_medium": "Email", "email_account": email_account}
    if mailbox == "inbox":
        f["sent_or_received"] = "Received"
    elif mailbox == "sent":
        f["sent_or_received"] = "Sent"
    return f

@frappe.whitelist()
def get_emails(email_account, mailbox="inbox", q=None, limit_start=0, limit=50):
    _ensure_portal_access()
    filters = _comm_filters(email_account, mailbox)
    or_filters = []
    if q:
        or_filters = [
            ["Communication", "subject", "like", f"%{q}%"],
            ["Communication", "sender", "like", f"%{q}%"],
            ["Communication", "recipients", "like", f"%{q}%"],
        ]
    rows = frappe.get_all(
        "Communication",
        filters=filters,
        or_filters=or_filters,
        fields=["name","subject","sender","recipients","communication_date","content"],
        order_by="communication_date desc, creation desc",
        limit_start=int(limit_start),
        limit=int(limit),
        ignore_permissions=1,
    )
    items = []
    for r in rows:
        preview = strip_html(r.content or "")[:220]
        items.append({
            "name": r.name,
            "subject": r.subject or "(no subject)",
            "sender": r.sender,
            "recipients": r.recipients,
            "communication_date": r.communication_date,
            "preview": preview,
        })
    total = frappe.db.count("Communication", filters=filters)
    return {"items": items, "total": total}

@frappe.whitelist()
def get_email(name):
    _ensure_portal_access()
    doc = frappe.get_doc("Communication", name)
    files = frappe.get_all(
        "File",
        filters={"attached_to_doctype": "Communication", "attached_to_name": name},
        fields=["file_name","file_url"],
        order_by="creation asc",
        ignore_permissions=1,
    )
    return {
        "name": doc.name,
        "subject": getattr(doc, "subject", None) or "(no subject)",
        "sender": getattr(doc, "sender", None),
        "recipients": getattr(doc, "recipients", None),
        "cc": getattr(doc, "cc", None),
        "bcc": getattr(doc, "bcc", None),
        "communication_date": getattr(doc, "communication_date", None),
        "content": getattr(doc, "content", "") or "",
        "attachments": files,
    }
