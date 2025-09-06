import frappe

@frappe.whitelist()
def ping(event="ping_mobile", name="TEST"):
    payload = {"msg": "hello", "name": name}
    frappe.publish_realtime(event, payload, user="*", after_commit=True)
    return "ok"
