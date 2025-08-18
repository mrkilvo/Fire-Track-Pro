import frappe


def get_context(context):
	user = frappe.session.user
	try:
		full_name = frappe.db.get_value("User", user, "full_name") or user
	except Exception:
		full_name = user
	context.full_name = full_name
	context.timezone_string = "8th August 2025 10:00 AEST"
	context.fpaa_fsa_no = "-"
	try:
		context.jobs_count = frappe.db.count("Job", {"owner": user}) if frappe.db.has_table("Job") else 3
	except Exception:
		context.jobs_count = 3
	try:
		context.open_tasks = (
			frappe.db.count("Task", {"status": "Open", "owner": user}) if frappe.db.has_table("Task") else 7
		)
	except Exception:
		context.open_tasks = 7
	try:
		context.dispatches_count = (
			frappe.db.count("Dispatch", {"owner": user}) if frappe.db.has_table("Dispatch") else 1
		)
	except Exception:
		context.dispatches_count = 1
	try:
		context.clients_count = (
			frappe.db.count("Customer", {"owner": user}) if frappe.db.has_table("Customer") else 12
		)
	except Exception:
		context.clients_count = 12
	return context
