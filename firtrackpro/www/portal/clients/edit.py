import frappe
from frappe import _


def get_context(context):
    name = frappe.form_dict.get("name")
    if frappe.request.method == "POST":
        # Save logic
        data = frappe.local.form_dict
        if name:
            doc = frappe.get_doc("Customer", name)
        else:
            doc = frappe.new_doc("Customer")
        doc.customer_name = data.get("customer_name")
        doc.customer_type = data.get("customer_type")
        doc.customer_group = data.get("customer_group")
        doc.territory = data.get("territory")
        doc.save()
        # Save/update credit limit
        credit_limit = data.get("credit_limit")
        if credit_limit is not None:
            cl = frappe.db.get_value(
                "Customer Credit Limit", {"parent": doc.name}, "name"
            )
            if cl:
                cl_doc = frappe.get_doc("Customer Credit Limit", cl)
                cl_doc.credit_limit = credit_limit
                cl_doc.save()
            else:
                cl_doc = frappe.get_doc(
                    {
                        "doctype": "Customer Credit Limit",
                        "parent": doc.name,
                        "parenttype": "Customer",
                        "parentfield": "credit_limits",
                        "credit_limit": credit_limit,
                    }
                )
                cl_doc.insert()
        # Save/update primary address
        primary_address = data.get("primary_address")
        if primary_address is not None:
            address_link = frappe.db.get_value(
                "Dynamic Link",
                {
                    "link_doctype": "Customer",
                    "link_name": doc.name,
                    "parenttype": "Address",
                },
                "parent",
            )
            if address_link:
                address = frappe.get_doc("Address", address_link)
                address.address_line1 = primary_address
                address.save()
            elif primary_address:
                address = frappe.get_doc(
                    {
                        "doctype": "Address",
                        "address_title": doc.customer_name,
                        "address_line1": primary_address,
                        "links": [{"link_doctype": "Customer", "link_name": doc.name}],
                    }
                )
                address.insert()
        # Save/update primary contact
        primary_contact = data.get("primary_contact")
        if primary_contact is not None:
            contact_link = frappe.db.get_value(
                "Dynamic Link",
                {
                    "link_doctype": "Customer",
                    "link_name": doc.name,
                    "parenttype": "Contact",
                },
                "parent",
            )
            if contact_link:
                contact = frappe.get_doc("Contact", contact_link)
                # Try to split into salutation/first/last name if possible
                parts = primary_contact.split()
                if len(parts) > 1:
                    contact.first_name = parts[1]
                    contact.last_name = " ".join(parts[2:]) if len(parts) > 2 else ""
                    contact.salutation = parts[0]
                else:
                    contact.first_name = primary_contact
                contact.save()
            elif primary_contact:
                # Try to split into salutation/first/last name if possible
                parts = primary_contact.split()
                contact_doc = {
                    "doctype": "Contact",
                    "first_name": parts[1] if len(parts) > 1 else primary_contact,
                    "last_name": " ".join(parts[2:]) if len(parts) > 2 else "",
                    "salutation": parts[0] if len(parts) > 1 else "",
                    "links": [{"link_doctype": "Customer", "link_name": doc.name}],
                }
                contact = frappe.get_doc(contact_doc)
                contact.insert()
        frappe.db.commit()
        context.client = doc
        context.saved = True
    else:
        if name:
            doc = frappe.get_doc("Customer", name)
        else:
            doc = frappe.new_doc("Customer")
        # Attach primary address, contact, and credit limit for display
        address_link = frappe.db.get_value(
            "Dynamic Link",
            {
                "link_doctype": "Customer",
                "link_name": doc.name,
                "parenttype": "Address",
            },
            "parent",
        )
        if address_link:
            address = frappe.get_doc("Address", address_link)
            doc.primary_address = address.get("address_line1", "")
            if address.get("city"):
                doc.primary_address += ", " + address.get("city")
            if address.get("phone"):
                doc.primary_address += " (" + address.get("phone") + ")"
        else:
            doc.primary_address = ""
        contact_link = frappe.db.get_value(
            "Dynamic Link",
            {
                "link_doctype": "Customer",
                "link_name": doc.name,
                "parenttype": "Contact",
            },
            "parent",
        )
        if contact_link:
            contact = frappe.get_doc("Contact", contact_link)
            doc.primary_contact = (
                contact.get("salutation", "") + " " + contact.get("first_name", "")
            )
            if contact.get("last_name"):
                doc.primary_contact += " " + contact.get("last_name")
            if contact.get("phone"):
                doc.primary_contact += " (" + contact.get("phone") + ")"
        else:
            doc.primary_contact = ""
        credit_limit = frappe.db.get_value(
            "Customer Credit Limit", {"parent": doc.name}, "credit_limit"
        )
        doc.credit_limit = credit_limit or ""
        context.client = doc
    # For dropdowns
    context.client_groups = frappe.get_all("Customer Group", fields=["name"])
    return context
