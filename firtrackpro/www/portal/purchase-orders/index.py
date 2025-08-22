import frappe

from firtrackpro.portal_utils import build_portal_context

no_cache = 1


def get_context(context):
	context.PAGE_TITLE = "Purchase Orders"
	context.actions = ["export"]
	context.columns = [
		"PO #",
		"Date",
		"Supplier",
		"Status",
		"Grand Total",
		"Schedule Date",
	]
	return build_portal_context(context, page_h1="Purchase Orders", force_login=True)
