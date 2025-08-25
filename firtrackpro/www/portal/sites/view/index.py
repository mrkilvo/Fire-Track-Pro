# firtrackpro/www/portal/sites/view/index.py
import frappe

from firtrackpro.portal_utils import build_portal_context, require_login

no_cache = 1


def get_context(context):
	require_login()

	# URL: /portal/sites/view?name=<ft_property.name>
	name = frappe.form_dict.get("name")
	if not name:
		frappe.throw("Missing ?name= parameter")

	context.PAGE_TITLE = "Property"
	context.property_name = name  # pass through for JS to fetch details
	# Render minimal shell; JS will populate tabs
	return build_portal_context(context, page_h1="Property", force_login=True)
