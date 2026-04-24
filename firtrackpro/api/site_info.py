# apps/firtrackpro/firtrackpro/api/site_info.py
import frappe

ONBOARDING_DEFAULT_KEY = "firtrackpro:portal_onboarding_complete"
PORTAL_ONBOARDING_ROUTE = "/portal/onboarding"


def _default_is_truthy(key: str) -> bool:
	value = str(frappe.db.get_default(key) or "").strip().lower()
	return value in {"1", "true", "yes", "on"}


def _set_default_bool(key: str, value: bool):
	frappe.db.set_default(key, "1" if value else "0")


def _count_enabled_users() -> int:
	return len(
		frappe.get_all(
			"User",
			filters={"enabled": 1},
			pluck="name",
		)
	)


def _count_integration_connections() -> int:
	for doctype in (
		"FT Integration Connection",
		"Portal Integration Connection",
		"Integration Connection",
	):
		if frappe.db.exists("DocType", doctype):
			return frappe.db.count(doctype)
	return 0


def _doctype_count(*doctypes: str) -> int:
	for doctype in doctypes:
		if frappe.db.exists("DocType", doctype):
			return frappe.db.count(doctype)
	return 0


@frappe.whitelist()
def get_site():
	"""Return the current Frappe site (used to pick the Socket.IO namespace)."""
	return {"site": frappe.local.site}


@frappe.whitelist()
def get_portal_onboarding_status():
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)

	user_doc = frappe.get_cached_doc("User", frappe.session.user)
	has_desk_access = bool(user_doc.has_desk_access())
	completed = _default_is_truthy(ONBOARDING_DEFAULT_KEY)

	return {
		"completed": completed,
		"route": PORTAL_ONBOARDING_ROUTE,
		"has_desk_access": has_desk_access,
		"company_count": _doctype_count("Company"),
		"enabled_user_count": _count_enabled_users(),
		"integration_connection_count": _count_integration_connections(),
		"customer_count": _doctype_count("Customer"),
		"supplier_count": _doctype_count("Supplier"),
		"site_count": _doctype_count("FT Property", "Property"),
		"asset_count": _doctype_count("FT Asset", "Asset", "Item"),
	}


@frappe.whitelist(methods=["POST"])
def complete_portal_onboarding():
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)

	user_doc = frappe.get_cached_doc("User", frappe.session.user)
	if not user_doc.has_desk_access():
		frappe.throw("Only desk users can complete portal onboarding.", frappe.PermissionError)

	_set_default_bool(ONBOARDING_DEFAULT_KEY, True)
	frappe.cache.delete_value("home_page")
	frappe.clear_cache(user=frappe.session.user)
	return get_portal_onboarding_status()


def apply_portal_site_defaults():
	changed = False

	if frappe.db.exists("DocType", "Website Settings"):
		website_settings = frappe.get_single("Website Settings")
		current_home_page = str(website_settings.home_page or "").strip()
		if current_home_page in {"", "login", "desk", "app", "me"}:
			website_settings.home_page = "index"
			website_settings.flags.ignore_permissions = True
			website_settings.save()
			changed = True

	if frappe.db.exists("DocType", "Portal Settings"):
		portal_home = frappe.db.get_single_value("Portal Settings", "default_portal_home")
		if not str(portal_home or "").strip():
			frappe.db.set_single_value("Portal Settings", "default_portal_home", "portal")
			changed = True

	if changed:
		frappe.cache.delete_value("home_page")
		frappe.clear_cache()
