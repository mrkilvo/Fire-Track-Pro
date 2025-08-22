import frappe
from firtrackpro.portal_utils import build_portal_context

no_cache = 1

def get_context(context):
    context.PAGE_TITLE = "Quotes"
    context.actions = ["export"]
    context.columns = [
        "Quote #",
        "Date",
        "Party",
        "Status",
        "Grand Total",
        "Valid Till",
    ]
    return build_portal_context(context, page_h1="Quotes", force_login=True)
