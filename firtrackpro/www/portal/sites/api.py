# apps/firtrackpro/firtrackpro/www/portal/sites/api.py
import json
from typing import Any, Dict

import frappe
from frappe import _
from firtrackpro.portal_utils import require_login


# -------------------------------
# Helpers
# -------------------------------

def _json_request() -> Dict[str, Any]:
    try:
        raw = frappe.request.data or b"{}"
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return frappe.parse_json(raw) or {}
    except Exception:
        return frappe._dict(frappe.local.form_dict or {})

def _find_customer(name_or_title: str) -> str | None:
    """Resolve Customer by exact name or by customer_name."""
    if not name_or_title:
        return None
    if frappe.db.exists("Customer", name_or_title):
        return name_or_title
    row = frappe.db.get_value("Customer", {"customer_name": name_or_title}, "name")
    return row

def _default_customer_group() -> str:
    # Prefer "All Customer Groups" if it exists
    if frappe.db.exists("Customer Group", "All Customer Groups"):
        return "All Customer Groups"
    row = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
    if row:
        return row
    # Last resort
    return "All Customer Groups"

def _default_territory() -> str:
    if frappe.db.exists("Territory", "All Territories"):
        return "All Territories"
    row = frappe.db.get_value("Territory", {"is_group": 0}, "name")
    if row:
        return row
    return "All Territories"


# -------------------------------
# Public APIs
# -------------------------------

@frappe.whitelist(methods=["GET"])
def search_customer(q: str = "", limit: int = 8):
    """Autocomplete Customer search for the New Site form."""
    require_login()
    q = (q or "").strip()
    if not q:
        return []
    rows = frappe.db.get_all(
        "Customer",
        filters={"customer_name": ["like", f"%{q}%"]},
        fields=["name", "customer_name", "customer_type"],
        order_by="modified desc",
        limit=frappe.utils.cint(limit) or 8,
    )
    return rows


@frappe.whitelist(methods=["POST"])
def create_customer(customer_name: str | None = None, customer_type: str | None = None, email: str | None = None, phone: str | None = None):
    """Create a minimal Customer (Company/Individual) with safe defaults."""
    require_login()

    # Read from form or JSON
    if not customer_name:
        payload = _json_request()
        customer_name = payload.get("customer_name")
        customer_type = payload.get("customer_type")
        email = payload.get("email")
        phone = payload.get("phone")

    customer_name = (customer_name or "").strip()
    if not customer_name:
        frappe.throw(_("Customer Name is required"))

    if not frappe.has_permission("Customer", ptype="create"):
        frappe.throw(_("Not permitted to create Customers"), frappe.PermissionError)

    doc = frappe.get_doc({
        "doctype": "Customer",
        "customer_name": customer_name,
        "customer_type": (customer_type or "Company"),
        "customer_group": _default_customer_group(),
        "territory": _default_territory(),
    })
    # Optional hints; ERPNext stores contacts separately, but keeping hints is fine if fields exist
    if email:
        try:
            doc.db_set("email_id", email, update_modified=False)
        except Exception:
            pass
    if phone:
        try:
            doc.db_set("mobile_no", phone, update_modified=False)
        except Exception:
            pass

    doc.insert(ignore_permissions=False)
    return {"name": doc.name, "customer_name": doc.customer_name, "customer_type": doc.customer_type}


@frappe.whitelist(methods=["POST"])
def create_property():
    """Create Address → FT Property → FT Property Access (+contacts).
    Returns: {"name": <property name>, "view_url": "/portal/sites/view?name=..."}
    """
    require_login()
    payload = _json_request()
    prop = frappe._dict(payload.get("property") or {})
    addr = frappe._dict(payload.get("address") or {})
    access = frappe._dict(payload.get("access") or {})
    contacts = payload.get("contacts") or []

    if not prop.property_name:
        frappe.throw(_("Display Name is required"))
    if not prop.property_customer:
        frappe.throw(_("Customer is required"))

    # resolve customer docname
    customer = _find_customer(prop.property_customer)
    if not customer:
        frappe.throw(_("Customer not found: {0}").format(prop.property_customer))

    # 1) Address (core)
    address_doc = frappe.get_doc({
        "doctype": "Address",
        "address_title": prop.property_name,
        "address_type": "Other",
        "address_line1": addr.address_line1,
        "address_line2": addr.get("address_line2"),
        "city": addr.city,
        "state": addr.state,
        "pincode": addr.get("pincode"),
        "country": addr.get("country") or "Australia",
        "latitude": addr.get("lat"),
        "longitude": addr.get("lng"),
    })
    address_doc.flags.ignore_permissions = True
    address_doc.insert()

    # 2) FT Property
    prop_doc = frappe.get_doc({
        "doctype": "FT Property",
        "property_name": prop.property_name,
        "property_customer": customer,
        "property_address": address_doc.name,
        "property_lat": addr.get("lat"),
        "property_lng": addr.get("lng"),
        "property_as1851_edition": prop.get("property_as1851_edition") or "2021",
        "property_notes": prop.get("property_notes"),
    })
    prop_doc.flags.ignore_permissions = True

    # Contacts child table (if present on your DocType)
    def _append_contact_row(c: Dict[str, Any]):
        full_name = (c.get("full_name") or "").strip()
        email = (c.get("email") or "").strip()
        phone = (c.get("phone") or "").strip()
        if not (full_name or email or phone):
            return
        # Resolve or create Contact
        contact_name = None
        if email:
            contact_name = frappe.db.get_value("Contact", {"email_id": email}, "name")
        if not contact_name and full_name:
            contact_name = frappe.db.get_value("Contact", {"first_name": full_name}, "name")
        if not contact_name:
            cdoc = frappe.get_doc({
                "doctype": "Contact",
                "first_name": full_name or (email or "Contact"),
                "email_id": email,
                "mobile_no": phone,
            })
            cdoc.flags.ignore_permissions = True
            cdoc.insert()
            contact_name = cdoc.name
        try:
            prop_doc.append("property_contacts", {
                "property_contact_contact": contact_name,
                "property_contact_role": c.get("role") or "other",
                "property_contact_is_primary": 1 if c.get("is_primary") else 0,
                "property_contact_phone": phone,
                "property_contact_email": email,
            })
        except Exception:
            # If the child table isn't present on FT Property, log and continue
            frappe.log_error("property_contacts child table missing on FT Property", "FT Property Contacts")

    for c in contacts:
        _append_contact_row(c)

    prop_doc.insert()

    # 3) FT Property Access (optional)
    if any([access.get("property_access_keysafe_code"),
            access.get("property_access_gate_code"),
            access.get("property_access_alarm_panel"),
            access.get("property_access_parking")]):
        acc_doc = frappe.get_doc({
            "doctype": "FT Property Access",
            "property_access_property": prop_doc.name,
            "property_access_keysafe_code": access.get("property_access_keysafe_code"),
            "property_access_gate_code": access.get("property_access_gate_code"),
            "property_access_alarm_panel": access.get("property_access_alarm_panel"),
            "property_access_parking": access.get("property_access_parking"),
        })
        acc_doc.flags.ignore_permissions = True
        acc_doc.insert()
        # Link back if parent has a field to store it
        try:
            prop_doc.db_set("property_access", acc_doc.name)
        except Exception:
            pass

    return {
        "name": prop_doc.name,
        "view_url": f"/portal/sites/view?name={frappe.utils.quote(prop_doc.name)}"
    }


@frappe.whitelist(methods=["POST"])
def delete_property(name: str | None = None):
    require_login()
    name = name or (frappe.form_dict.get("name") if frappe.form_dict else None)
    if not name:
        frappe.throw(_("Missing property name"))
    if not frappe.db.exists("FT Property", name):
        frappe.throw(_("Property not found"), title=_("Not Found"))
    try:
        access_name = frappe.db.get_value("FT Property", name, "property_access")
        if access_name and frappe.db.exists("FT Property Access", access_name):
            frappe.delete_doc("FT Property Access", access_name, ignore_permissions=True, force=1)
    except Exception:
        pass
    frappe.delete_doc("FT Property", name, ignore_permissions=True, force=1)
    return "ok"
