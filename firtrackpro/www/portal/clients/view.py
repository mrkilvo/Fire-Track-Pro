import frappe


def get_context(context):
	name = frappe.form_dict.get("name")
	if not name:
		frappe.throw("Missing customer name")
	client = frappe.get_doc("Customer", name)
	context.client = client
	return context
