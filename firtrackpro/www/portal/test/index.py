import frappe

from firtrackpro.portal_utils import build_portal_context

no_cache = 1


def get_context(context):
	return build_portal_context(context, page_h1="Portal Test Page", force_login=True)
