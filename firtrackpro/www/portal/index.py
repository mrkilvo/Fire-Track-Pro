import frappe

from firtrackpro.portal_utils import build_portal_context, require_login

no_cache = 1


def get_context(context):
	require_login()
	context.KPIS = [
		{"label": "Open Jobs", "value": 42, "delta": "+8 this week"},
		{"label": "Overdue Invoices", "value": 5, "delta": "-2 vs last week"},
		{"label": "Active Defects", "value": 27, "delta": "+3 today"},
		{"label": "Technicians On Site", "value": 9, "delta": "of 14 total"},
	]
	context.JOBS_STATUS = [{"s": "Open", "n": 14}, {"s": "In Progress", "n": 18}, {"s": "Completed", "n": 10}]
	context.INVOICE_MIX = [{"s": "Paid", "n": 62}, {"s": "Overdue", "n": 12}, {"s": "Draft", "n": 26}]
	context.RECENT = [
		{"time": "09:12", "txt": "JOB-1042 completed at Site 118 by Alex Lee"},
		{"time": "10:01", "txt": "AFSS-NSW-471 submitted for Harbour Tower"},
		{"time": "10:45", "txt": "Invoice INV-2025-117 sent to Globex Pty Ltd"},
		{"time": "11:08", "txt": "Defect DEF-2044 approved by Client"},
	]
	context.PAGE_TITLE = "Dashboard"
	return build_portal_context(context, page_h1="Dashboard", force_login=True)
