import frappe

from firtrackpro.portal_utils import build_portal_context

no_cache = 1


def get_context(context):
	context.actions = []
	context.PAGE_TITLE = "Job Events (GPS)"
	# page_h1 powers the compact top bar in portal_base.html
	return build_portal_context(context, page_h1="Job Events (GPS)", force_login=True)
