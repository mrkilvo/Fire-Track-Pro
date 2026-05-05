# apps/firtrackpro/firtrackpro/api/site_info.py
import frappe
from importlib import import_module

ONBOARDING_DEFAULT_KEY = "firtrackpro:portal_onboarding_complete"
INITIAL_TENANT_SETUP_KEY = "firtrackpro:initial_tenant_setup_complete"
SITE_DEFAULTS_SEEDED_KEY = "firtrackpro:site_defaults_seeded_once"
PORTAL_ONBOARDING_ROUTE = "/portal/onboarding"
PORTAL_HOME_FALLBACK = "portal"


def _default_is_truthy(key: str) -> bool:
	value = str(frappe.db.get_default(key) or "").strip().lower()
	return value in {"1", "true", "yes", "on"}


def _set_default_bool(key: str, value: bool):
	frappe.db.set_default(key, "1" if value else "0")


def _has_system_settings_setup_complete() -> bool:
	if not frappe.db.exists("DocType", "System Settings"):
		return False
	try:
		meta = frappe.get_meta("System Settings")
		return bool(meta and meta.has_field("setup_complete"))
	except Exception:
		return False


def _set_system_setup_complete() -> bool:
	if not _has_system_settings_setup_complete():
		return False
	try:
		frappe.db.set_single_value("System Settings", "setup_complete", 1)
		return True
	except Exception:
		return False


def _is_truthy(value) -> bool:
	return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _mark_installed_apps_setup_complete() -> bool:
	if not frappe.db.exists("DocType", "Installed Application"):
		return False
	try:
		meta = frappe.get_meta("Installed Application")
		if not meta or not meta.has_field("is_setup_complete"):
			return False
		updated = False
		for app_name in ("frappe", "erpnext", "firtrackpro"):
			if frappe.db.exists("Installed Application", {"app_name": app_name}):
				frappe.db.set_value(
					"Installed Application",
					{"app_name": app_name},
					"is_setup_complete",
					1,
					update_modified=False,
				)
				updated = True
		return updated
	except Exception:
		return False


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
	try:
		meta = frappe.get_meta(doctype)
		if not meta or not meta.has_field(fieldname):
			return False
		frappe.db.set_single_value(doctype, fieldname, value)
		return True
	except Exception:
		return False


def _set_if_field(doc, meta, fieldname: str, value) -> bool:
	if meta and meta.has_field(fieldname):
		doc.set(fieldname, value)
		return True
	return False


def _normalized_country_code(value: str) -> str:
	raw = str(value or "").strip().lower()
	if raw in {"au", "aus", "australia"}:
		return "AU"
	if raw in {"uk", "gb", "gbr", "united kingdom", "great britain", "england"}:
		return "GB"
	return raw.upper() if raw else "AU"


def _resolve_tenant_country() -> tuple[str, str]:
	company_name = ""
	if frappe.db.exists("DocType", "Global Defaults"):
		company_name = str(frappe.db.get_single_value("Global Defaults", "default_company") or "").strip()

	country_name = ""
	if company_name and frappe.db.exists("Company", company_name) and frappe.db.has_column("Company", "country"):
		country_name = str(frappe.db.get_value("Company", company_name, "country") or "").strip()

	if not country_name and frappe.db.exists("DocType", "Company") and frappe.db.has_column("Company", "country"):
		country_name = str(frappe.db.get_value("Company", {}, "country") or "").strip()

	if not country_name:
		country_name = "Australia"

	return _normalized_country_code(country_name), country_name


def _ensure_default_address_template(country_name: str) -> bool:
	if not frappe.db.exists("DocType", "Address Template"):
		return False
	try:
		meta = frappe.get_meta("Address Template")
		default_name = str(frappe.db.get_value("Address Template", {"is_default": 1}, "name") or "").strip()
		if default_name:
			return False

		doc = frappe.new_doc("Address Template")
		label = "FireTrack Default Address Template"
		body = "{{ address_line1 }}\n{% if address_line2 %}{{ address_line2 }}\n{% endif %}{% if city %}{{ city }}{% endif %}{% if state %}, {{ state }}{% endif %}{% if pincode %} {{ pincode }}{% endif %}\n{% if country %}{{ country }}{% endif %}"
		changed = False
		changed = _set_if_field(doc, meta, "template_name", label) or changed
		changed = _set_if_field(doc, meta, "country", country_name or "Australia") or changed
		changed = _set_if_field(doc, meta, "is_default", 1) or changed
		changed = _set_if_field(doc, meta, "template", body) or changed
		if not changed:
			return False
		doc.insert(ignore_permissions=True)
		return True
	except Exception:
		frappe.log_error(frappe.get_traceback(), "FireTrack default Address Template seed failed")
		return False


COUNTRY_TASK_SEED_MODULES: dict[str, list[str]] = {
	# Australia: current default seed pack.
	"AU": [
		"firtrackpro.patches.v16_0.seed_network_task_setup_and_items",
	],
	# UK: wire-in path ready; add UK seed modules here as they are created.
	"GB": [],
}


def _run_seed_module(module_path: str) -> bool:
	module = import_module(module_path)
	execute = getattr(module, "execute", None)
	if not callable(execute):
		return False
	execute()
	return True


def _ensure_task_setup_seeds(country_code: str) -> bool:
	modules = COUNTRY_TASK_SEED_MODULES.get(country_code) or COUNTRY_TASK_SEED_MODULES.get("AU") or []
	ran_any = False
	for module_path in modules:
		try:
			if _run_seed_module(module_path):
				ran_any = True
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"FireTrack task setup seed failed: {module_path}")
	return ran_any


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


@frappe.whitelist()
def get_initial_tenant_setup_status():
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	setup_complete = _default_is_truthy(INITIAL_TENANT_SETUP_KEY)
	system_setup_complete = bool(
		_has_system_settings_setup_complete()
		and _is_truthy(frappe.db.get_single_value("System Settings", "setup_complete"))
	)
	return {
		"initial_tenant_setup_complete": setup_complete,
		"system_setup_complete": system_setup_complete,
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


@frappe.whitelist(methods=["POST"])
def complete_initial_tenant_setup():
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	user_doc = frappe.get_cached_doc("User", frappe.session.user)
	if not user_doc.has_desk_access():
		frappe.throw("Only desk users can complete initial tenant setup.", frappe.PermissionError)

	_set_default_bool(INITIAL_TENANT_SETUP_KEY, True)
	_set_system_setup_complete()
	_mark_installed_apps_setup_complete()
	frappe.cache.delete_value("home_page")
	frappe.clear_cache(user=frappe.session.user)
	return get_initial_tenant_setup_status()


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
	country_code, country_name = _resolve_tenant_country()

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

	# Keep base operational defaults available on fresh tenant setup.
	if _ensure_default_address_template(country_name):
		changed = True

	# Re-apply idempotent task setup/item seeds based on tenant country.
	if _ensure_task_setup_seeds(country_code):
		changed = True

	if changed:
		frappe.cache.delete_value("home_page")
		frappe.clear_cache()


@frappe.whitelist()
def seed_site_defaults_once(force: int | None = None):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	force_run = str(force or 0).strip() in {"1", "true", "yes", "on"}
	already_seeded = _default_is_truthy(SITE_DEFAULTS_SEEDED_KEY)
	if already_seeded and not force_run:
		return {
			"ok": True,
			"seeded": False,
			"already_seeded": True,
			"message": "Site defaults were already seeded for this tenant.",
		}

	apply_portal_site_defaults()
	_set_default_bool(SITE_DEFAULTS_SEEDED_KEY, True)
	frappe.clear_cache()
	return {
		"ok": True,
		"seeded": True,
		"already_seeded": False,
		"message": "Site defaults seeded successfully.",
	}
