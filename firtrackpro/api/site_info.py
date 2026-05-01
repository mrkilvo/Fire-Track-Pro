# apps/firtrackpro/firtrackpro/api/site_info.py
import frappe

ONBOARDING_DEFAULT_KEY = "firtrackpro:portal_onboarding_complete"
PORTAL_ONBOARDING_ROUTE = "/portal/onboarding"
PORTAL_HOME_FALLBACK = "portal"


def _default_is_truthy(key: str) -> bool:
	value = str(frappe.db.get_default(key) or "").strip().lower()
	return value in {"1", "true", "yes", "on"}


def _set_default_bool(key: str, value: bool):
	frappe.db.set_default(key, "1" if value else "0")


def _normalize_route(path: str) -> str:
	route = str(path or "").strip()
	if not route:
		return "/portal"
	if not route.startswith("/"):
		route = f"/{route}"
	if route != "/" and route.endswith("/"):
		route = route.rstrip("/")
	return route or "/portal"


def _resolve_portal_home_route() -> str:
	portal_home = ""
	if frappe.db.exists("DocType", "Portal Settings"):
		portal_home = str(frappe.db.get_single_value("Portal Settings", "default_portal_home") or "").strip()
	if not portal_home:
		portal_home = PORTAL_HOME_FALLBACK
	return _normalize_route(portal_home)


def _resolve_public_logo_url() -> str:
	if frappe.db.exists("DocType", "Website Settings"):
		logo = str(frappe.db.get_single_value("Website Settings", "app_logo") or "").strip()
		if logo:
			return logo

	if frappe.db.exists("DocType", "Navbar Settings"):
		logo = str(frappe.db.get_single_value("Navbar Settings", "app_logo") or "").strip()
		if logo:
			return logo

	logos = frappe.get_hooks("app_logo_url") or []
	for logo in logos:
		value = str(logo or "").strip()
		if value:
			return value

	return ""


def _resolve_public_brand_name() -> str:
	if frappe.db.exists("DocType", "Website Settings"):
		brand = str(frappe.db.get_single_value("Website Settings", "brand") or "").strip()
		if brand:
			return brand

	if frappe.db.exists("DocType", "Global Defaults"):
		company = str(frappe.db.get_single_value("Global Defaults", "default_company") or "").strip()
		if company:
			return company

	return "FireTrack Pro"


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


def _safe_set_single(doctype: str, fieldname: str, value: str) -> bool:
	if not frappe.db.exists("DocType", doctype):
		return False
	if not frappe.db.has_column(doctype, fieldname):
		return False
	frappe.db.set_single_value(doctype, fieldname, value)
	return True


def _first_company_logo(company: str) -> str:
	if not company or not frappe.db.exists("Company", company):
		return ""
	for fieldname in ("company_logo", "logo", "company_logo_url"):
		if frappe.db.has_column("Company", fieldname):
			logo = str(frappe.db.get_value("Company", company, fieldname) or "").strip()
			if logo:
				return logo
	for fieldname in ("file_url",):
		if frappe.db.has_column("File", fieldname):
			row = frappe.get_all(
				"File",
				filters={"attached_to_doctype": "Company", "attached_to_name": company, "is_private": 0},
				fields=["file_url", "creation"],
				order_by="creation desc",
				limit=1,
			)
			if row:
				return str(row[0].get("file_url") or "").strip()
	return ""


@frappe.whitelist()
def sync_public_branding_from_company(company: str | None = None):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)

	company_name = str(company or "").strip()
	if not company_name and frappe.db.exists("DocType", "Global Defaults"):
		company_name = str(frappe.db.get_single_value("Global Defaults", "default_company") or "").strip()
	if not company_name:
		frappe.throw("Company is required.")
	if not frappe.db.exists("Company", company_name):
		frappe.throw(f"Company not found: {company_name}")

	brand_name = company_name
	logo_url = _first_company_logo(company_name)
	updated = False

	if brand_name:
		updated = _safe_set_single("Website Settings", "app_name", brand_name) or updated
		updated = _safe_set_single("Website Settings", "brand", brand_name) or updated

	if logo_url:
		updated = _safe_set_single("Website Settings", "app_logo", logo_url) or updated
		updated = _safe_set_single("Navbar Settings", "app_logo", logo_url) or updated
		updated = _safe_set_single("Website Settings", "splash_image", logo_url) or updated

	if updated:
		frappe.clear_cache()

	return {
		"brand_name": _resolve_public_brand_name(),
		"logo_url": _resolve_public_logo_url(),
		"updated": bool(updated),
	}


@frappe.whitelist(allow_guest=True)
def get_site():
	"""Return the current Frappe site (used to pick the Socket.IO namespace)."""
	return {"site": frappe.local.site}


@frappe.whitelist(allow_guest=True)
def get_public_branding():
	return {
		"site": str(frappe.local.site or ""),
		"brand_name": _resolve_public_brand_name(),
		"logo_url": _resolve_public_logo_url(),
	}


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


def force_portal_home_on_session_creation(login_manager=None):
	"""Force portal home after login so new sites do not bounce to /desk or /app."""
	if frappe.session.user == "Guest":
		return

	home_route = _resolve_portal_home_route()
	frappe.local.response["home_page"] = home_route

	redirect_to = str(frappe.local.response.get("redirect_to") or "").strip()
	if redirect_to in {"/desk", "/app"} or redirect_to.startswith("/desk/") or redirect_to.startswith("/app/"):
		frappe.local.response["redirect_to"] = home_route



def apply_portal_site_defaults():
	changed = False

	if frappe.db.exists("DocType", "Website Settings"):
		website_settings = frappe.get_single("Website Settings")
		current_home_page = str(website_settings.home_page or "").strip()
		if current_home_page in {"", "login", "desk", "/desk", "app", "/app", "me"}:
			website_settings.home_page = "index"
			website_settings.flags.ignore_permissions = True
			website_settings.save()
			changed = True

	if frappe.db.exists("DocType", "Portal Settings"):
		portal_home = frappe.db.get_single_value("Portal Settings", "default_portal_home")
		if not str(portal_home or "").strip():
			frappe.db.set_single_value("Portal Settings", "default_portal_home", PORTAL_HOME_FALLBACK)
			changed = True

	current_global_home = str(frappe.db.get_default("home_page") or "").strip().lower()
	if current_global_home in {"", "desk", "/desk", "app", "/app", "login", "/login"}:
		frappe.db.set_default("home_page", _resolve_portal_home_route().lstrip("/"))
		changed = True

	if frappe.db.exists("DocType", "User") and frappe.db.has_column("User", "home_page"):
		frappe.db.sql(
			"""
				update `tabUser`
				set home_page = %s
				where enabled = 1
				  and name not in ('Guest')
				  and ifnull(home_page, '') in ('', 'desk', '/desk', 'app', '/app', 'login', '/login')
			""",
			(_resolve_portal_home_route().lstrip("/"),),
		)
		if frappe.db.affected_rows() > 0:
			changed = True

	if changed:
		frappe.cache.delete_value("home_page")
		frappe.clear_cache()
