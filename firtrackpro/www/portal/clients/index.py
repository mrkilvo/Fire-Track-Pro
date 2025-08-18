import frappe


def get_context(context):
	user = frappe.session.user
	if user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/portal/clients"
		raise frappe.Redirect

	# Get filters from query params
	search = frappe.form_dict.get("search", "").strip()
	client_type = frappe.form_dict.get("type", "")
	client_group = frappe.form_dict.get("group", "")

	filters = {}
	if client_type:
		filters["customer_type"] = client_type
	if client_group:
		filters["customer_group"] = client_group
	if search:
		filters["customer_name"] = ["like", f"%{search}%"]

	clients = frappe.get_all(
		"Customer",
		fields=[
			"name",
			"customer_name",
			"customer_type",
			"customer_group",
			"territory",
			"creation",
			"modified",
		],
		filters=filters,
		order_by="modified desc",
	)
	# Attach primary address, contact, and credit limit
	for client in clients:
		# Primary Address
		address_link = frappe.db.get_value(
			"Dynamic Link",
			{
				"link_doctype": "Customer",
				"link_name": client["name"],
				"parenttype": "Address",
			},
			"parent",
		)
		if address_link:
			address = frappe.get_doc("Address", address_link)
			client["primary_address"] = address.get("address_line1", "")
			if address.get("city"):
				client["primary_address"] += ", " + address.get("city")
			if address.get("phone"):
				client["primary_address"] += " (" + address.get("phone") + ")"
		else:
			client["primary_address"] = "-"
		# Primary Contact
		contact_link = frappe.db.get_value(
			"Dynamic Link",
			{
				"link_doctype": "Customer",
				"link_name": client["name"],
				"parenttype": "Contact",
			},
			"parent",
		)
		if contact_link:
			contact = frappe.get_doc("Contact", contact_link)
			client["primary_contact"] = contact.get("salutation", "") + " " + contact.get("first_name", "")
			if contact.get("last_name"):
				client["primary_contact"] += " " + contact.get("last_name")
			if contact.get("phone"):
				client["primary_contact"] += " (" + contact.get("phone") + ")"
		else:
			client["primary_contact"] = "-"
		# Credit Limit
		credit_limit = frappe.db.get_value(
			"Customer Credit Limit", {"parent": client["name"]}, "credit_limit"
		)
		client["credit_limit"] = credit_limit or "-"

	# For group filter dropdown
	client_groups = frappe.get_all("Customer Group", fields=["name"], order_by="name asc")

	context.clients = clients
	context.client_groups = client_groups
	context.title = "Clients"
	return context
