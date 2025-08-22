import frappe

from firtrackpro.portal_utils import build_portal_context

no_cache = 1


def get_context(context):
	context.PAGE_TITLE = "Invoices"
	context.actions = ["export"]
	context.columns = [
		"Invoice #",
		"Date",
		"Customer",
		"Status",
		"Grand Total",
		"Outstanding",
		"Due Date",
	]

	has_invoices = False
	invoice_count = 0
	try:
		# Will succeed even when there are 0 rows; returns 0
		invoice_count = frappe.db.count("Sales Invoice")
		has_invoices = True  # DocType exists
	except Exception:
		# DocType missing or ERPNext not installed; keep UI alive
		has_invoices = False
		invoice_count = 0

	context.has_invoices = has_invoices
	context.invoice_count = invoice_count

	return build_portal_context(context, page_h1="Invoices", force_login=True)
