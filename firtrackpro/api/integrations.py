import base64
import json
import os
import re
import shlex
import subprocess
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlparse

import frappe
from frappe.utils.file_manager import save_file

try:
	import requests
except Exception:  # pragma: no cover
	requests = None

PROVIDERS = ["MYOB", "Xero", "QuickBooks", "Custom"]
DEFAULTS_KEY = "firtrackpro:integration_configs_json"
GOOGLE_AUTOCOMPLETE_URL = "https://maps.googleapis.com/maps/api/place/autocomplete/json"
GOOGLE_PLACE_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"
GOOGLE_KEY_CANDIDATES = (
	"google_maps_api_key",
	"google_places_api_key",
	"google_api_key",
)
FIRELINK_BASE_KEY_CANDIDATES = (
	"firelink_base_url",
	"firtrackpro_firelink_base_url",
)
FIRELINK_API_KEY_CANDIDATES = (
	"firelink_api_key",
	"firtrackpro_firelink_api_key",
)
FIRELINK_API_SECRET_CANDIDATES = (
	"firelink_api_secret",
	"firtrackpro_firelink_api_secret",
)
FIRELINK_USERNAME_CANDIDATES = (
	"firelink_username",
	"firtrackpro_firelink_username",
)
FIRELINK_PASSWORD_CANDIDATES = (
	"firelink_password",
	"firtrackpro_firelink_password",
)
FIRELINK_BRIDGE_TOKEN_CANDIDATES = (
	"firelink_bridge_token",
	"firtrackpro_firelink_bridge_token",
)
FIRELINK_BASE_FALLBACK = "https://firelink.firetrackpro.com.au"
FIRELINK_ADDRESS_DOCTYPES = ("FL Address", "Address")

FIRELINK_PROVISION_COMMAND_CANDIDATES = (
	"firelink_provision_command",
	"firtrackpro_firelink_provision_command",
)

FIRELINK_DOMAIN_PROVISION_COMMAND_CANDIDATES = (
	"firelink_domain_provision_command",
	"firtrackpro_firelink_domain_provision_command",
)

FIRELINK_SITE_STATUS_COMMAND_CANDIDATES = (
	"firelink_site_status_command",
	"firtrackpro_firelink_site_status_command",
)

PROVIDER_DEFAULTS = {
	"MYOB": {
		"baseUrl": "https://api.myob.com/accountright",
		"authUrl": "https://secure.myob.com/oauth2/account/authorize",
		"tokenUrl": "https://secure.myob.com/oauth2/v1/authorize",
		"scopes": "CompanyFile offline_access",
	},
	"Xero": {
		"baseUrl": "https://api.xero.com",
		"authUrl": "https://login.xero.com/identity/connect/authorize",
		"tokenUrl": "https://identity.xero.com/connect/token",
		"scopes": "openid profile email accounting.transactions accounting.contacts offline_access",
	},
	"QuickBooks": {
		"baseUrl": "https://quickbooks.api.intuit.com",
		"authUrl": "https://appcenter.intuit.com/connect/oauth2",
		"tokenUrl": "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
		"scopes": "com.intuit.quickbooks.accounting",
	},
	"Custom": {
		"baseUrl": "",
		"authUrl": "",
		"tokenUrl": "",
		"scopes": "",
	},
}


def _as_bool(value: Any) -> bool:
	if isinstance(value, bool):
		return value
	if value is None:
		return False
	return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_str(value: Any) -> str:
	return str(value or "").strip()


def _as_int(value: Any, default: int = 0) -> int:
	try:
		return int(float(value))
	except Exception:
		return int(default)


def _as_float(value: Any, default: float = 0.0) -> float:
	try:
		return float(value)
	except Exception:
		return float(default)


def _safe_json_load(raw: str) -> dict[str, Any]:
	try:
		parsed = json.loads(raw or "{}")
		return parsed if isinstance(parsed, dict) else {}
	except Exception:
		return {}


def _load_records() -> dict[str, Any]:
	raw = _as_str(frappe.db.get_default(DEFAULTS_KEY))
	records = _safe_json_load(raw)
	out: dict[str, Any] = {}
	for provider in PROVIDERS:
		row = records.get(provider) if isinstance(records.get(provider), dict) else {}
		defaults = PROVIDER_DEFAULTS.get(provider, {})
		out[provider] = {
			"provider": provider,
			"enabled": _as_bool(row.get("enabled")),
			"name": _as_str(row.get("name")) or provider,
			"baseUrl": _as_str(row.get("baseUrl")) or _as_str(defaults.get("baseUrl")),
			"authUrl": _as_str(row.get("authUrl")) or _as_str(defaults.get("authUrl")),
			"tokenUrl": _as_str(row.get("tokenUrl")) or _as_str(defaults.get("tokenUrl")),
			"clientId": _as_str(row.get("clientId")),
			"clientSecret": _as_str(row.get("clientSecret")),
			"tenantId": _as_str(row.get("tenantId")),
			"scopes": _as_str(row.get("scopes")) or _as_str(defaults.get("scopes")),
			"webhookSecret": _as_str(row.get("webhookSecret")),
			"syncCustomers": _as_bool(row.get("syncCustomers")),
			"syncInvoices": _as_bool(row.get("syncInvoices")),
			"syncPayments": _as_bool(row.get("syncPayments")),
			"syncSuppliers": _as_bool(row.get("syncSuppliers")),
		}
	return out


def _save_records(records: dict[str, Any]) -> None:
	frappe.db.set_default(DEFAULTS_KEY, json.dumps(records))


def _get_google_maps_api_key() -> str:
	site_conf = frappe.get_site_config() or {}
	for key in GOOGLE_KEY_CANDIDATES:
		value = _as_str(site_conf.get(key) or frappe.conf.get(key))
		if value:
			return value
	for key in ("GOOGLE_MAPS_API_KEY", "GOOGLE_PLACES_API_KEY"):
		value = _as_str(os.environ.get(key))
		if value:
			return value
	try:
		common_site_config_path = frappe.get_site_path("..", "common_site_config.json")
		if common_site_config_path and os.path.exists(common_site_config_path):
			with open(common_site_config_path, encoding="utf-8") as handle:
				common_conf = json.load(handle) or {}
			if isinstance(common_conf, dict):
				for key in GOOGLE_KEY_CANDIDATES:
					value = _as_str(common_conf.get(key))
					if value:
						return value
	except Exception:
		pass
	try:
		reference_site = _as_str(
			site_conf.get("google_maps_reference_site")
			or frappe.conf.get("google_maps_reference_site")
			or "dev.firetrackpro.com.au"
		)
		if reference_site:
			reference_config_path = frappe.get_site_path("..", reference_site, "site_config.json")
			if reference_config_path and os.path.exists(reference_config_path):
				with open(reference_config_path, encoding="utf-8") as handle:
					reference_conf = json.load(handle) or {}
				if isinstance(reference_conf, dict):
					for key in GOOGLE_KEY_CANDIDATES:
						value = _as_str(reference_conf.get(key))
						if value:
							return value
	except Exception:
		pass
	frappe.throw(
		"Google Places API key is not configured on the server. "
		"Set google_maps_api_key in site_config.json, common_site_config.json, or GOOGLE_MAPS_API_KEY.",
		frappe.ValidationError,
	)


def _google_http_get(url: str, params: dict[str, Any]) -> dict[str, Any]:
	if requests is None:
		frappe.throw("Google lookup is unavailable (requests library missing).")
	key = _get_google_maps_api_key()
	query = dict(params or {})
	query["key"] = key
	try:
		res = requests.get(url, params=query, timeout=12)
		res.raise_for_status()
		payload = res.json() if hasattr(res, "json") else {}
	except Exception as exc:
		frappe.throw(f"Google lookup failed: {exc}")

	status = _as_str(payload.get("status"))
	if status not in {"OK", "ZERO_RESULTS"}:
		err = _as_str(payload.get("error_message") or payload.get("status")) or "Unknown Google API error"
		frappe.throw(f"Google lookup failed: {err}")
	return payload if isinstance(payload, dict) else {}


def _pick_component(components: list[dict[str, Any]], kind: str, short: bool = False) -> str:
	for comp in components:
		types = comp.get("types") if isinstance(comp, dict) else None
		if isinstance(types, list) and kind in types:
			key = "short_name" if short else "long_name"
			return _as_str(comp.get(key))
	return ""


def _norm(value: Any) -> str:
	return _as_str(value).lower().strip()


_ADDRESS_TOKEN_MAP = {
	"street": "st",
	"st.": "st",
	"road": "rd",
	"rd.": "rd",
	"avenue": "ave",
	"ave.": "ave",
	"boulevard": "blvd",
	"drive": "dr",
	"dr.": "dr",
	"lane": "ln",
	"ln.": "ln",
	"court": "ct",
	"ct.": "ct",
	"place": "pl",
	"pl.": "pl",
	"terrace": "tce",
	"highway": "hwy",
	"mount": "mt",
}


def _address_key(value: Any) -> str:
	raw = _norm(value)
	if not raw:
		return ""
	tokens = re.split(r"[^a-z0-9]+", raw)
	normed = [_ADDRESS_TOKEN_MAP.get(tok, tok) for tok in tokens if tok]
	return " ".join(normed)


def _site_conf_value(*keys: str) -> str:
	site_conf = frappe.get_site_config() or {}
	for key in keys:
		val = _as_str(site_conf.get(key) or frappe.conf.get(key))
		if val:
			return val
	return ""


def _firelink_base_url() -> str:
	return _site_conf_value(*FIRELINK_BASE_KEY_CANDIDATES) or FIRELINK_BASE_FALLBACK


def _firelink_bridge_token() -> str:
	return _site_conf_value(*FIRELINK_BRIDGE_TOKEN_CANDIDATES)


def _firelink_auth_headers() -> dict[str, str]:
	api_key = _site_conf_value(*FIRELINK_API_KEY_CANDIDATES)
	api_secret = _site_conf_value(*FIRELINK_API_SECRET_CANDIDATES)
	if api_key and api_secret:
		return {"Authorization": f"token {api_key}:{api_secret}"}
	return {}


def _firelink_http(
	method: str,
	path: str,
	*,
	params: dict[str, Any] | None = None,
	data: dict[str, Any] | None = None,
	timeout: int = 18,
	headers: dict[str, str] | None = None,
) -> dict[str, Any]:
	if requests is None:
		frappe.throw("FireLink sync is unavailable (requests library missing).")
	base = _firelink_base_url().rstrip("/")
	url = f"{base}{path}"
	req_headers = {"Accept": "application/json"}
	req_headers.update(_firelink_auth_headers())
	if headers:
		req_headers.update(headers)
	try:
		resp = requests.request(
			method=method.upper(),
			url=url,
			params=params or None,
			data=data or None,
			headers=req_headers,
			timeout=timeout,
		)
	except Exception as exc:
		frappe.throw(f"FireLink request failed: {exc}")
	if int(resp.status_code or 0) >= 400:
		detail = _as_str(getattr(resp, "text", "")).strip()[:400]
		frappe.throw(f"FireLink request failed ({resp.status_code}): {detail or 'Unknown error'}")
	try:
		payload = resp.json() if hasattr(resp, "json") else {}
	except Exception:
		payload = {}
	return payload if isinstance(payload, dict) else {}


def _firelink_login_if_needed() -> None:
	# Kept as a no-op for now: backend FireLink calls should rely on token auth
	# or server-side allowlist policy, not browser/session cookies.
	return


def _firelink_get_doctype_fields(doctype: str) -> set[str]:
	payload = _firelink_http(
		"GET",
		"/api/method/frappe.desk.form.load.getdoctype",
		params={"doctype": doctype},
	)
	out: set[str] = {"name"}
	queue: list[Any] = [payload]
	seen: set[int] = set()
	while queue:
		cur = queue.pop(0)
		if not isinstance(cur, dict | list):
			continue
		obj_id = id(cur)
		if obj_id in seen:
			continue
		seen.add(obj_id)
		if isinstance(cur, list):
			queue.extend(cur)
			continue
		if "fieldname" in cur and "fieldtype" in cur:
			fieldname = _as_str(cur.get("fieldname"))
			if fieldname:
				out.add(fieldname)
		queue.extend(list(cur.values()))
	return out


def _pick_existing_field(field_names: set[str], candidates: tuple[str, ...]) -> str:
	for key in candidates:
		if key in field_names:
			return key
	return ""


def _strong_match(existing: dict[str, Any], incoming: dict[str, Any]) -> bool:
	row_line1 = _address_key(existing.get("address_line1"))
	in_line1 = _address_key(incoming.get("address_line1"))
	if not row_line1 or not in_line1 or row_line1 != in_line1:
		return False
	row_place_id = _norm(existing.get("place_id"))
	in_place_id = _norm(incoming.get("place_id"))
	if in_place_id:
		return bool(row_place_id and row_place_id == in_place_id)
	row_post = _norm(existing.get("pincode"))
	in_post = _norm(incoming.get("pincode"))
	if row_post and in_post and row_post == in_post:
		return True
	row_city = _norm(existing.get("city"))
	in_city = _norm(incoming.get("city"))
	row_state = _norm(existing.get("state"))
	in_state = _norm(incoming.get("state"))
	return bool(
		row_city and in_city and row_state and in_state and row_city == in_city and row_state == in_state
	)


def _find_fl_property_by_address_id(address_id: str) -> str:
	if not address_id or not frappe.db.exists("DocType", "FL Property"):
		return ""
	rows = frappe.get_all(
		"FL Property",
		fields=["name", "property_address_json"],
		filters=[["property_address_json", "like", f"%{address_id}%"]],
		limit_page_length=200,
	)
	for row in rows:
		raw = _as_str(row.get("property_address_json"))
		if not raw:
			continue
		try:
			payload = json.loads(raw)
		except Exception:
			payload = {}
		if _as_str((payload or {}).get("address_id")) == address_id:
			return _as_str(row.get("name"))
	return ""


def _normalize_remote_row(row: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
	def pick(kind: str) -> Any:
		field = mapping.get(kind)
		return row.get(field) if field else None

	return {
		"name": _as_str(row.get("name")),
		"address_title": _as_str(pick("title")) or None,
		"address_line1": _as_str(pick("line1")) or None,
		"address_line2": _as_str(pick("line2")) or None,
		"city": _as_str(pick("city")) or None,
		"state": _as_str(pick("state")) or None,
		"pincode": _as_str(pick("post")) or None,
		"country": _as_str(pick("country")) or None,
		"place_id": _as_str(pick("place_id")) or None,
	}


def _resolve_or_create_address_on_current_site(incoming: dict[str, Any]) -> dict[str, Any]:
	last_error = ""
	for doctype in FIRELINK_ADDRESS_DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue
		try:
			meta = frappe.get_meta(doctype)
			field_names = set(
				[
					"name",
					*[
						str(d.fieldname or "").strip()
						for d in (meta.fields or [])
						if getattr(d, "fieldname", None)
					],
				]
			)
		except Exception as exc:
			last_error = _as_str(exc)
			continue

		line1_field = _pick_existing_field(
			field_names,
			(
				"address_line1",
				"fl_address_line1",
				"line1",
				"street_address",
				"address",
				"street",
				"street1",
				"address1",
			),
		)
		if not line1_field:
			last_error = f"{doctype} missing line1 field"
			continue
		mapping = {
			"title": _pick_existing_field(
				field_names, ("address_title", "fl_address_title", "title", "name")
			),
			"line1": line1_field,
			"line2": _pick_existing_field(
				field_names, ("address_line2", "fl_address_line2", "line2", "street2", "address2")
			),
			"city": _pick_existing_field(field_names, ("city", "suburb", "town")),
			"state": _pick_existing_field(field_names, ("state", "province")),
			"post": _pick_existing_field(field_names, ("pincode", "postcode", "postal_code", "zip")),
			"country": _pick_existing_field(field_names, ("country",)),
			"place_id": _pick_existing_field(
				field_names, ("google_place_id", "place_id", "google_places_id", "google_placeid")
			),
		}

		or_filters: list[list[Any]] = [[doctype, line1_field, "like", f"%{incoming['address_line1']}%"]]
		if mapping["place_id"] and incoming.get("place_id"):
			or_filters.insert(0, [doctype, mapping["place_id"], "=", incoming["place_id"]])
		if mapping["city"] and incoming.get("city"):
			or_filters.append([doctype, mapping["city"], "like", f"%{incoming['city']}%"])

		select_fields = list(
			dict.fromkeys(
				[
					f
					for f in [
						"name",
						mapping["line1"],
						mapping["line2"],
						mapping["city"],
						mapping["state"],
						mapping["post"],
						mapping["country"],
						mapping["place_id"],
						mapping["title"],
					]
					if f
				]
			)
		)
		rows = frappe.get_all(doctype, fields=select_fields, or_filters=or_filters, limit_page_length=50)
		for row in rows:
			normalized = _normalize_remote_row(row, mapping)
			if _strong_match(normalized, incoming):
				return {
					"created": False,
					"firelink_doctype": doctype,
					"firelink_address_id": normalized.get("name"),
					"address": normalized,
				}

		doc = frappe.new_doc(doctype)
		doc.set(mapping["line1"], incoming["address_line1"])
		if mapping["title"]:
			doc.set(mapping["title"], incoming.get("address_title") or incoming["address_line1"])
		if mapping["line2"] and incoming.get("address_line2"):
			doc.set(mapping["line2"], incoming.get("address_line2"))
		if mapping["city"] and incoming.get("city"):
			doc.set(mapping["city"], incoming.get("city"))
		if mapping["state"] and incoming.get("state"):
			doc.set(mapping["state"], incoming.get("state"))
		if mapping["post"] and incoming.get("pincode"):
			doc.set(mapping["post"], incoming.get("pincode"))
		if mapping["country"]:
			doc.set(mapping["country"], incoming.get("country") or "Australia")
		if mapping["place_id"] and incoming.get("place_id"):
			doc.set(mapping["place_id"], incoming.get("place_id"))
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		refreshed = frappe.get_doc(doctype, doc.name).as_dict()
		normalized = _normalize_remote_row(refreshed, mapping)
		return {
			"created": True,
			"firelink_doctype": doctype,
			"firelink_address_id": normalized.get("name") or doc.name,
			"address": normalized,
		}

	frappe.throw(last_error or "FireLink local resolve/create failed")


def _is_valid_bridge_call() -> bool:
	expected = _firelink_bridge_token()
	provided = _as_str(getattr(frappe.local, "form_dict", {}).get("bridge_token"))
	if expected and provided and provided == expected:
		return True
	origin = _as_str(getattr(getattr(frappe.local, "request", None), "headers", {}).get("Origin"))
	referer = _as_str(getattr(getattr(frappe.local, "request", None), "headers", {}).get("Referer"))
	text = f"{origin} {referer}".lower()
	return ".firetrackpro.com.au" in text


@frappe.whitelist()
def list_configs():
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	return {"records": _load_records()}


@frappe.whitelist(methods=["POST"])
def save_config(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)

	provider = _as_str(kwargs.get("provider") or kwargs.get("integration_provider")).strip()
	if provider not in PROVIDERS:
		frappe.throw("provider is required and must be one of: MYOB, Xero, QuickBooks, Custom")

	records = _load_records()
	current = records.get(provider, {"provider": provider})

	current.update(
		{
			"provider": provider,
			"enabled": _as_bool(kwargs.get("enabled")),
			"name": _as_str(kwargs.get("name")) or provider,
			"baseUrl": _as_str(kwargs.get("base_url") or kwargs.get("baseUrl")),
			"authUrl": _as_str(kwargs.get("auth_url") or kwargs.get("authUrl")),
			"tokenUrl": _as_str(kwargs.get("token_url") or kwargs.get("tokenUrl")),
			"clientId": _as_str(kwargs.get("client_id") or kwargs.get("clientId")),
			"clientSecret": _as_str(kwargs.get("client_secret") or kwargs.get("clientSecret")),
			"tenantId": _as_str(kwargs.get("tenant_id") or kwargs.get("tenantId")),
			"scopes": _as_str(kwargs.get("scopes")),
			"webhookSecret": _as_str(kwargs.get("webhook_secret") or kwargs.get("webhookSecret")),
			"syncCustomers": _as_bool(kwargs.get("sync_customers") or kwargs.get("syncCustomers")),
			"syncInvoices": _as_bool(kwargs.get("sync_invoices") or kwargs.get("syncInvoices")),
			"syncPayments": _as_bool(kwargs.get("sync_payments") or kwargs.get("syncPayments")),
			"syncSuppliers": _as_bool(kwargs.get("sync_suppliers") or kwargs.get("syncSuppliers")),
		}
	)

	records[provider] = current
	_save_records(records)
	frappe.clear_cache(user=frappe.session.user)
	return {"ok": True, "provider": provider}


@frappe.whitelist(methods=["POST"])
def test_connection(**kwargs):
	provider = _as_str(kwargs.get("provider") or kwargs.get("integration_provider"))
	client_id = _as_str(kwargs.get("client_id") or kwargs.get("clientId"))
	client_secret = _as_str(kwargs.get("client_secret") or kwargs.get("clientSecret"))
	defaults = PROVIDER_DEFAULTS.get(provider, {})
	base_url = _as_str(kwargs.get("base_url") or kwargs.get("baseUrl")) or _as_str(defaults.get("baseUrl"))
	auth_url = _as_str(kwargs.get("auth_url") or kwargs.get("authUrl")) or _as_str(defaults.get("authUrl"))
	token_url = _as_str(kwargs.get("token_url") or kwargs.get("tokenUrl")) or _as_str(
		defaults.get("tokenUrl")
	)

	if not provider:
		frappe.throw("provider is required")

	test_url = base_url or auth_url or token_url
	if not test_url:
		frappe.throw("API Base URL, Auth URL, or Token URL is required")

	if requests is None:
		return f"{provider}: configuration saved. Network test skipped (requests not available)."

	try:
		response = requests.get(test_url, timeout=8, allow_redirects=True)
		status = int(response.status_code)
		if 200 <= status < 500:
			if not client_id or not client_secret:
				return f"{provider}: endpoint reachable ({status}). OAuth credentials are still required for real sync."
			return f"{provider}: endpoint reachable ({status})"
		frappe.throw(f"{provider}: endpoint test failed with status {status}")
	except Exception as exc:
		frappe.throw(f"{provider}: endpoint test failed - {exc}")


@frappe.whitelist(methods=["POST"])
def sync_entity(**kwargs):
	frappe.throw(
		"External sync pipeline is not yet wired for this provider. Save/test works; OAuth token + entity mapping is still pending."
	)


@frappe.whitelist(methods=["POST"])
def sync_customer(**kwargs):
	return sync_entity(**kwargs)


@frappe.whitelist(methods=["POST"])
def sync_supplier(**kwargs):
	return sync_entity(**kwargs)


@frappe.whitelist(methods=["POST"])
def sync_invoice(**kwargs):
	return sync_entity(**kwargs)


@frappe.whitelist(methods=["POST"])
def sync_payment(**kwargs):
	return sync_entity(**kwargs)


@frappe.whitelist()
def google_places_autocomplete(query=None, country="au"):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)

	q = _as_str(query)
	if len(q) < 3:
		return []

	params: dict[str, Any] = {
		"input": q,
		"types": "address",
	}
	country_code = _as_str(country).lower()
	if country_code:
		params["components"] = f"country:{country_code}"

	payload = _google_http_get(GOOGLE_AUTOCOMPLETE_URL, params)
	rows = payload.get("predictions")
	if not isinstance(rows, list):
		return []

	out: list[dict[str, str]] = []
	for row in rows[:10]:
		if not isinstance(row, dict):
			continue
		description = _as_str(row.get("description"))
		place_id = _as_str(row.get("place_id"))
		if not description or not place_id:
			continue
		out.append({"description": description, "place_id": place_id})
	return out


@frappe.whitelist()
def google_place_details(place_id=None):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)

	google_place_id = _as_str(place_id)
	if not google_place_id:
		frappe.throw("place_id is required", frappe.ValidationError)

	payload = _google_http_get(
		GOOGLE_PLACE_DETAILS_URL,
		{
			"place_id": google_place_id,
			"fields": "place_id,name,formatted_address,address_component,geometry",
		},
	)
	result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
	components = result.get("address_components")
	components = components if isinstance(components, list) else []

	street_number = _pick_component(components, "street_number")
	route = _pick_component(components, "route")
	subpremise = _pick_component(components, "subpremise")
	locality = _pick_component(components, "locality")
	sublocality = _pick_component(components, "sublocality")
	city = locality or sublocality or _pick_component(components, "administrative_area_level_2")
	state = _pick_component(components, "administrative_area_level_1", short=True) or _pick_component(
		components, "administrative_area_level_1"
	)
	pincode = _pick_component(components, "postal_code")
	country = _pick_component(components, "country") or "Australia"
	line1 = " ".join([piece for piece in [street_number, route] if piece]).strip()
	line2 = subpremise

	geometry = result.get("geometry") if isinstance(result.get("geometry"), dict) else {}
	location = geometry.get("location") if isinstance(geometry.get("location"), dict) else {}
	lat = location.get("lat")
	lng = location.get("lng")
	try:
		lat = float(lat) if lat is not None else None
	except Exception:
		lat = None
	try:
		lng = float(lng) if lng is not None else None
	except Exception:
		lng = None

	formatted_address = _as_str(result.get("formatted_address"))
	address_title = (
		_as_str(result.get("name")) or line1 or formatted_address.split(",")[0].strip() or "Site Address"
	)
	address_line1 = line1 or address_title

	return {
		"place_id": google_place_id,
		"address_title": address_title,
		"address_line1": address_line1,
		"address_line2": line2 or None,
		"city": city or None,
		"state": state or None,
		"pincode": pincode or None,
		"country": country,
		"lat": lat,
		"lng": lng,
		"formatted_address": formatted_address or None,
	}


@frappe.whitelist(methods=["POST"])
def firelink_address_resolve_or_create(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	incoming = {
		"address_title": _as_str(kwargs.get("address_title")) or None,
		"address_line1": _as_str(kwargs.get("address_line1")),
		"address_line2": _as_str(kwargs.get("address_line2")) or None,
		"city": _as_str(kwargs.get("city")) or None,
		"state": _as_str(kwargs.get("state")) or None,
		"pincode": _as_str(kwargs.get("pincode")) or None,
		"country": _as_str(kwargs.get("country")) or "Australia",
		"place_id": _as_str(kwargs.get("place_id")) or None,
	}
	if not incoming["address_line1"]:
		frappe.throw("address_line1 is required", frappe.ValidationError)

	# If this is already the FireLink site, resolve/create locally.
	base_url = _firelink_base_url().rstrip("/").lower()
	current_host = _as_str(getattr(frappe.local, "site", "")).lower()
	if current_host and current_host in base_url:
		return _resolve_or_create_address_on_current_site(incoming)

	# Primary path for separate FireLink server: call dedicated bridge endpoint.
	bridge_payload = dict(incoming)
	token = _firelink_bridge_token()
	if token:
		bridge_payload["bridge_token"] = token
	try:
		bridge = _firelink_http(
			"POST",
			"/api/method/firtrackpro.api.integrations.firelink_address_bridge",
			data=bridge_payload,
			headers={"Content-Type": "application/x-www-form-urlencoded"},
		)
		message = bridge.get("message") if isinstance(bridge.get("message"), dict) else bridge
		if isinstance(message, dict):
			firelink_id = _as_str(message.get("firelink_address_id"))
			if firelink_id:
				return message
	except Exception:
		pass

	frappe.throw(
		"FireLink bridge endpoint is unavailable on firelink.firetrackpro.com.au. "
		"Deploy this updated firtrackpro app to FireLink and configure firelink_bridge_token on both sites."
	)

	# Legacy fallback for benches where bridge is not yet deployed.
	_firelink_login_if_needed()
	last_error = ""
	for doctype in FIRELINK_ADDRESS_DOCTYPES:
		try:
			field_names = _firelink_get_doctype_fields(doctype)
		except Exception as exc:
			last_error = _as_str(exc)
			continue

		line1_field = _pick_existing_field(
			field_names,
			(
				"address_line1",
				"fl_address_line1",
				"line1",
				"street_address",
				"address",
				"street",
				"street1",
				"address1",
			),
		)
		if not line1_field:
			last_error = f"{doctype} missing line1 field"
			continue
		mapping = {
			"title": _pick_existing_field(
				field_names, ("address_title", "fl_address_title", "title", "name")
			),
			"line1": line1_field,
			"line2": _pick_existing_field(
				field_names, ("address_line2", "fl_address_line2", "line2", "street2", "address2")
			),
			"city": _pick_existing_field(field_names, ("city", "suburb", "town")),
			"state": _pick_existing_field(field_names, ("state", "province")),
			"post": _pick_existing_field(field_names, ("pincode", "postcode", "postal_code", "zip")),
			"country": _pick_existing_field(field_names, ("country",)),
			"place_id": _pick_existing_field(
				field_names, ("google_place_id", "place_id", "google_places_id", "google_placeid")
			),
		}

		search_terms: list[list[Any]] = [[doctype, line1_field, "like", f"%{incoming['address_line1']}%"]]
		if mapping["place_id"] and incoming["place_id"]:
			search_terms.insert(0, [doctype, mapping["place_id"], "=", incoming["place_id"]])
		if mapping["city"] and incoming["city"]:
			search_terms.append([doctype, mapping["city"], "like", f"%{incoming['city']}%"])
		if mapping["title"] and incoming["address_title"]:
			search_terms.append([doctype, mapping["title"], "like", f"%{incoming['address_title']}%"])

		fields = ["name", mapping["line1"]]
		for key in ("title", "line2", "city", "state", "post", "country", "place_id"):
			if mapping.get(key):
				fields.append(mapping[key])
		unique_fields = list(dict.fromkeys([f for f in fields if f]))

		list_payload = _firelink_http(
			"GET",
			f"/api/resource/{quote(doctype, safe='')}",
			params={
				"fields": json.dumps(unique_fields),
				"limit_page_length": "50",
				"or_filters": json.dumps(search_terms),
			},
		)
		rows = list_payload.get("data")
		rows = rows if isinstance(rows, list) else []
		best_row = None
		for row in rows:
			if not isinstance(row, dict):
				continue
			normalized = _normalize_remote_row(row, mapping)
			if _strong_match(normalized, incoming):
				best_row = row
				break
		if best_row:
			normalized = _normalize_remote_row(best_row, mapping)
			return {
				"created": False,
				"firelink_doctype": doctype,
				"firelink_address_id": normalized.get("name"),
				"address": normalized,
			}

		create_doc: dict[str, Any] = {"doctype": doctype, mapping["line1"]: incoming["address_line1"]}
		if mapping["title"]:
			create_doc[mapping["title"]] = incoming["address_title"] or incoming["address_line1"]
		if mapping["line2"] and incoming["address_line2"]:
			create_doc[mapping["line2"]] = incoming["address_line2"]
		if mapping["city"] and incoming["city"]:
			create_doc[mapping["city"]] = incoming["city"]
		if mapping["state"] and incoming["state"]:
			create_doc[mapping["state"]] = incoming["state"]
		if mapping["post"] and incoming["pincode"]:
			create_doc[mapping["post"]] = incoming["pincode"]
		if mapping["country"]:
			create_doc[mapping["country"]] = incoming["country"] or "Australia"
		if mapping["place_id"] and incoming["place_id"]:
			create_doc[mapping["place_id"]] = incoming["place_id"]

		created_payload = _firelink_http(
			"POST",
			"/api/method/frappe.client.insert",
			data={"doc": json.dumps(create_doc)},
			headers={"Content-Type": "application/x-www-form-urlencoded"},
		)
		name = _as_str(
			(created_payload.get("message") or {}).get("name")
			if isinstance(created_payload.get("message"), dict)
			else created_payload.get("name")
		)
		if not name:
			last_error = f"{doctype} create failed (no name returned)"
			continue
		doc_payload = _firelink_http(
			"GET",
			f"/api/resource/{quote(doctype, safe='')}/{quote(name, safe='')}",
			params={"fields": json.dumps(unique_fields)},
		)
		doc_row = doc_payload.get("data")
		doc_row = doc_row if isinstance(doc_row, dict) else {"name": name}
		normalized = _normalize_remote_row(doc_row, mapping)
		return {
			"created": True,
			"firelink_doctype": doctype,
			"firelink_address_id": normalized.get("name") or name,
			"address": normalized,
		}

	frappe.throw(last_error or "FireLink sync failed")


@frappe.whitelist(allow_guest=True, methods=["POST"])
def firelink_address_bridge(**kwargs):
	if not _is_valid_bridge_call():
		frappe.throw("Bridge token or approved firetrackpro origin is required", frappe.PermissionError)
	incoming = {
		"address_title": _as_str(kwargs.get("address_title")) or None,
		"address_line1": _as_str(kwargs.get("address_line1")),
		"address_line2": _as_str(kwargs.get("address_line2")) or None,
		"city": _as_str(kwargs.get("city")) or None,
		"state": _as_str(kwargs.get("state")) or None,
		"pincode": _as_str(kwargs.get("pincode")) or None,
		"country": _as_str(kwargs.get("country")) or "Australia",
		"place_id": _as_str(kwargs.get("place_id")) or None,
	}
	if not incoming["address_line1"]:
		frappe.throw("address_line1 is required", frappe.ValidationError)
	return _resolve_or_create_address_on_current_site(incoming)


def _is_firelink_local_site() -> bool:
	base_url = _firelink_base_url().rstrip("/").lower()
	current_host = _as_str(getattr(frappe.local, "site", "")).lower()
	return bool(current_host and current_host in base_url)


def _remote_bridge_payload(kwargs: dict[str, Any]) -> dict[str, Any]:
	payload = {k: v for k, v in (kwargs or {}).items() if v is not None}
	token = _firelink_bridge_token()
	if token:
		payload["bridge_token"] = token
	return payload


def _firelink_remote_bridge_call(path: str, payload: dict[str, Any]) -> dict[str, Any]:
	bridge = _firelink_http(
		"POST",
		path,
		data=payload,
		headers={"Content-Type": "application/x-www-form-urlencoded"},
	)
	message = bridge.get("message") if isinstance(bridge.get("message"), dict) else bridge
	if isinstance(message, dict):
		return message
	frappe.throw("Invalid FireLink bridge response")


def _sub_fields() -> list[str]:
	return [
		"name",
		"site_host",
		"site_alias",
		"customer",
		"subscription_plan",
		"subscription_status",
		"base_users_included",
		"extra_users_purchased",
		"allowed_users_total",
		"billing_cycle",
		"next_invoice_date",
		"subscription_reference",
		"quotation_reference",
		"sales_invoice_reference",
		"auto_repeat_reference",
		"base_item_code",
		"extra_user_item_code",
		"monthly_base_price",
		"monthly_extra_user_price",
		"monthly_extra_users_amount",
		"monthly_total_amount",
		"notes",
		"modified",
	]


def _plan_fields() -> list[str]:
	return [
		"name",
		"plan_name",
		"plan_code",
		"description",
		"billing_cycle",
		"base_fee",
		"base_users_included",
		"extra_user_fee",
		"default_extra_users",
		"base_item_code",
		"extra_user_item_code",
		"is_active",
		"sort_order",
		"modified",
	]


def _billing_cycle_to_frequency(cycle: str) -> str:
	normalized = _as_str(cycle).lower()
	if normalized == "annual":
		return "Yearly"
	if normalized == "quarterly":
		return "Quarterly"
	return "Monthly"


def _local_list_plans() -> list[dict[str, Any]]:
	if not frappe.db.exists("DocType", "FL Subscription Plan"):
		return []
	return frappe.get_all(
		"FL Subscription Plan",
		fields=_plan_fields(),
		order_by="sort_order asc, modified desc",
		limit_page_length=500,
	)


def _local_get_plan(name: str) -> dict[str, Any]:
	doc = frappe.get_doc("FL Subscription Plan", name)
	out = doc.as_dict()
	return {k: out.get(k) for k in _plan_fields()}


def _local_create_plan(kwargs: dict[str, Any]) -> dict[str, Any]:
	plan_code = _as_str(kwargs.get("plan_code"))
	plan_name = _as_str(kwargs.get("plan_name")) or plan_code
	if not plan_code:
		frappe.throw("plan_code is required", frappe.ValidationError)
	if not plan_name:
		frappe.throw("plan_name is required", frappe.ValidationError)
	doc = frappe.get_doc(
		{
			"doctype": "FL Subscription Plan",
			"plan_name": plan_name,
			"plan_code": plan_code,
			"description": _as_str(kwargs.get("description")) or None,
			"billing_cycle": _as_str(kwargs.get("billing_cycle")) or "Monthly",
			"base_fee": _as_float(kwargs.get("base_fee"), 0.0),
			"base_users_included": _as_int(kwargs.get("base_users_included"), 0),
			"extra_user_fee": _as_float(kwargs.get("extra_user_fee"), 0.0),
			"default_extra_users": _as_int(kwargs.get("default_extra_users"), 0),
			"base_item_code": _as_str(kwargs.get("base_item_code")) or None,
			"extra_user_item_code": _as_str(kwargs.get("extra_user_item_code")) or None,
			"is_active": 1 if _as_bool(kwargs.get("is_active") if "is_active" in kwargs else True) else 0,
			"sort_order": _as_int(kwargs.get("sort_order"), 0),
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return _local_get_plan(doc.name)


def _local_update_plan(kwargs: dict[str, Any]) -> dict[str, Any]:
	name = _as_str(kwargs.get("name"))
	if not name:
		frappe.throw("name is required", frappe.ValidationError)
	doc = frappe.get_doc("FL Subscription Plan", name)
	for key in (
		"plan_name",
		"plan_code",
		"description",
		"billing_cycle",
		"base_item_code",
		"extra_user_item_code",
	):
		if key in kwargs and kwargs.get(key) is not None:
			doc.set(key, _as_str(kwargs.get(key)) or None)
	for key in ("base_fee", "extra_user_fee"):
		if key in kwargs and kwargs.get(key) is not None and str(kwargs.get(key)).strip() != "":
			doc.set(key, _as_float(kwargs.get(key), 0.0))
	for key in ("base_users_included", "default_extra_users", "sort_order"):
		if key in kwargs and kwargs.get(key) is not None and str(kwargs.get(key)).strip() != "":
			doc.set(key, _as_int(kwargs.get(key), 0))
	if "is_active" in kwargs:
		doc.set("is_active", 1 if _as_bool(kwargs.get("is_active")) else 0)
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return _local_get_plan(doc.name)


def _local_find_plan_by_code(plan_code: str) -> dict[str, Any] | None:
	code = _as_str(plan_code)
	if not code:
		return None
	rows = frappe.get_all(
		"FL Subscription Plan",
		fields=_plan_fields(),
		filters={"plan_code": code},
		limit_page_length=1,
	)
	return rows[0] if rows else None


def _local_upsert_plan_by_code(kwargs: dict[str, Any]) -> dict[str, Any]:
	existing = _local_find_plan_by_code(_as_str(kwargs.get("plan_code")))
	if existing and existing.get("name"):
		payload = dict(kwargs)
		payload["name"] = existing.get("name")
		return _local_update_plan(payload)
	return _local_create_plan(kwargs)


def _local_find_subscription_by_site(site_host: str) -> dict[str, Any] | None:
	normalized = _normalize_site_host(site_host)
	if not normalized:
		return None
	queries = [normalized]
	if normalized.startswith("www."):
		queries.append(normalized[4:])
	for key in queries:
		rows = frappe.get_all(
			"FL Site Subscription",
			fields=_sub_fields(),
			filters={"site_host": key},
			order_by="modified desc",
			limit_page_length=1,
		)
		if rows:
			return rows[0]
	return None


def _local_upsert_subscription_by_site(kwargs: dict[str, Any]) -> dict[str, Any]:
	site_host = _normalize_site_host(kwargs.get("site_host"))
	if not site_host:
		frappe.throw("site_host is required", frappe.ValidationError)
	existing = _local_find_subscription_by_site(site_host)
	payload = dict(kwargs)
	payload["site_host"] = site_host
	if existing and existing.get("name"):
		payload["name"] = existing.get("name")
		return _local_update_subscription(payload)
	return _local_create_subscription(payload)


def _local_list_subscriptions() -> list[dict[str, Any]]:
	if not frappe.db.exists("DocType", "FL Site Subscription"):
		return []
	return frappe.get_all(
		"FL Site Subscription",
		fields=_sub_fields(),
		order_by="modified desc",
		limit_page_length=500,
	)


def _local_get_subscription(name: str) -> dict[str, Any]:
	doc = frappe.get_doc("FL Site Subscription", name)
	out = doc.as_dict()
	return {k: out.get(k) for k in _sub_fields()}


def _normalize_site_host(raw: str) -> str:
	host = _as_str(raw).strip().lower()
	if not host:
		return ""
	if "://" in host:
		try:
			host = (urlparse(host).hostname or host).strip().lower()
		except Exception:
			pass
	host = host.split("/", 1)[0].strip().lower()
	if ":" in host:
		host = host.split(":", 1)[0].strip().lower()
	return host


def _local_subscription_quota(site_host: str) -> dict[str, Any]:
	if not frappe.db.exists("DocType", "FL Site Subscription"):
		return {
			"found": False,
			"site_host": _normalize_site_host(site_host),
			"allowed_users": None,
			"subscription_status": "",
			"source": "FL Site Subscription",
		}
	normalized = _normalize_site_host(site_host)
	if not normalized:
		frappe.throw("site_host is required", frappe.ValidationError)
	queries = [normalized]
	if normalized.startswith("www."):
		queries.append(normalized[4:])
	for key in queries:
		rows = frappe.get_all(
			"FL Site Subscription",
			fields=_sub_fields(),
			filters={"site_host": key},
			order_by="modified desc",
			limit_page_length=1,
		)
		if not rows:
			continue
		row = rows[0]
		base = int(float(row.get("base_users_included") or 0))
		extra = int(float(row.get("extra_users_purchased") or 0))
		allowed = row.get("allowed_users_total")
		allowed_int = int(float(allowed)) if str(allowed or "").strip() else max(0, base + extra)
		return {
			"found": True,
			"site_host": key,
			"allowed_users": max(0, allowed_int),
			"subscription_status": _as_str(row.get("subscription_status")) or "Active",
			"source": "FL Site Subscription.allowed_users_total",
			"row": row,
		}
	return {
		"found": False,
		"site_host": normalized,
		"allowed_users": None,
		"subscription_status": "",
		"source": "FL Site Subscription",
	}


def _local_create_subscription(kwargs: dict[str, Any]) -> dict[str, Any]:
	base_users = _as_int(kwargs.get("base_users_included"), 0)
	extra_users = _as_int(kwargs.get("extra_users_purchased"), 0)
	allowed_total = kwargs.get("allowed_users_total")
	allowed_users = (
		_as_int(allowed_total, base_users + extra_users)
		if str(allowed_total or "").strip()
		else max(0, base_users + extra_users)
	)
	doc = frappe.get_doc(
		{
			"doctype": "FL Site Subscription",
			"site_host": _normalize_site_host(kwargs.get("site_host")),
			"site_alias": _as_str(kwargs.get("site_alias")) or None,
			"customer": _as_str(kwargs.get("customer")),
			"subscription_plan": _as_str(kwargs.get("subscription_plan")) or None,
			"subscription_status": _as_str(kwargs.get("subscription_status")) or "Active",
			"base_users_included": max(0, base_users),
			"extra_users_purchased": max(0, extra_users),
			"allowed_users_total": max(0, allowed_users),
			"billing_cycle": _as_str(kwargs.get("billing_cycle")) or "Monthly",
			"next_invoice_date": _as_str(kwargs.get("next_invoice_date")) or None,
			"subscription_reference": _as_str(kwargs.get("subscription_reference")) or None,
			"quotation_reference": _as_str(kwargs.get("quotation_reference")) or None,
			"sales_invoice_reference": _as_str(kwargs.get("sales_invoice_reference")) or None,
			"auto_repeat_reference": _as_str(kwargs.get("auto_repeat_reference")) or None,
			"base_item_code": _as_str(kwargs.get("base_item_code")) or None,
			"extra_user_item_code": _as_str(kwargs.get("extra_user_item_code")) or None,
			"monthly_base_price": _as_float(kwargs.get("monthly_base_price"), 0.0),
			"monthly_extra_user_price": _as_float(kwargs.get("monthly_extra_user_price"), 0.0),
			"monthly_extra_users_amount": _as_float(kwargs.get("monthly_extra_users_amount"), 0.0),
			"monthly_total_amount": _as_float(kwargs.get("monthly_total_amount"), 0.0),
			"notes": _as_str(kwargs.get("notes")) or None,
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return _local_get_subscription(doc.name)


def _local_update_subscription(kwargs: dict[str, Any]) -> dict[str, Any]:
	name = _as_str(kwargs.get("name"))
	if not name:
		frappe.throw("name is required", frappe.ValidationError)
	doc = frappe.get_doc("FL Site Subscription", name)
	for key in (
		"site_host",
		"site_alias",
		"customer",
		"subscription_plan",
		"subscription_status",
		"billing_cycle",
		"next_invoice_date",
		"subscription_reference",
		"quotation_reference",
		"sales_invoice_reference",
		"auto_repeat_reference",
		"base_item_code",
		"extra_user_item_code",
		"notes",
	):
		if key in kwargs and kwargs.get(key) is not None:
			val = _as_str(kwargs.get(key))
			doc.set(key, _normalize_site_host(val) if key == "site_host" else (val or None))
	for key in ("base_users_included", "extra_users_purchased", "allowed_users_total"):
		if key in kwargs and kwargs.get(key) is not None and str(kwargs.get(key)).strip() != "":
			doc.set(key, _as_int(kwargs.get(key), 0))
	for key in (
		"monthly_base_price",
		"monthly_extra_user_price",
		"monthly_extra_users_amount",
		"monthly_total_amount",
	):
		if key in kwargs and kwargs.get(key) is not None and str(kwargs.get(key)).strip() != "":
			doc.set(key, _as_float(kwargs.get(key), 0.0))
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return _local_get_subscription(doc.name)


def _rb_fields() -> list[str]:
	return [
		"name",
		"reference_doctype",
		"reference_document",
		"frequency",
		"start_date",
		"end_date",
		"next_schedule_date",
		"disabled",
		"modified",
	]


def _local_list_recurring() -> list[dict[str, Any]]:
	return frappe.get_all(
		"Auto Repeat",
		fields=_rb_fields(),
		order_by="modified desc",
		limit_page_length=500,
	)


def _local_get_recurring(name: str) -> dict[str, Any]:
	doc = frappe.get_doc("Auto Repeat", name)
	out = doc.as_dict()
	return {k: out.get(k) for k in _rb_fields()}


def _local_create_recurring(kwargs: dict[str, Any]) -> dict[str, Any]:
	doc = frappe.get_doc(
		{
			"doctype": "Auto Repeat",
			"reference_doctype": _as_str(kwargs.get("reference_doctype")),
			"reference_document": _as_str(kwargs.get("reference_document")),
			"frequency": _as_str(kwargs.get("frequency")) or "Monthly",
			"start_date": _as_str(kwargs.get("start_date")),
			"end_date": _as_str(kwargs.get("end_date")) or None,
			"disabled": 1 if _as_str(kwargs.get("disabled")) in {"1", "true", "True"} else 0,
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return _local_get_recurring(doc.name)


def _local_update_recurring(kwargs: dict[str, Any]) -> dict[str, Any]:
	name = _as_str(kwargs.get("name"))
	if not name:
		frappe.throw("name is required", frappe.ValidationError)
	doc = frappe.get_doc("Auto Repeat", name)
	for key in ("frequency", "start_date", "end_date"):
		if key in kwargs and kwargs.get(key) is not None:
			doc.set(key, _as_str(kwargs.get(key)) or None)
	if "disabled" in kwargs:
		doc.set("disabled", 1 if _as_str(kwargs.get("disabled")) in {"1", "true", "True"} else 0)
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return _local_get_recurring(doc.name)


def _pick_non_group_link_value(doctype: str, requested: Any, fallback: str = "") -> str:
	requested_name = _as_str(requested)
	fallback_name = _as_str(fallback)

	def _is_group(name: str) -> bool:
		if not name:
			return False
		if not frappe.db.exists(doctype, name):
			return False
		try:
			return _as_bool(frappe.db.get_value(doctype, name, "is_group"))
		except Exception:
			return False

	for candidate in (requested_name, fallback_name):
		if candidate and frappe.db.exists(doctype, candidate) and not _is_group(candidate):
			return candidate

	try:
		rows = frappe.get_all(
			doctype,
			fields=["name"],
			filters={"is_group": 0},
			order_by="name asc",
			limit_page_length=1,
		)
		if rows:
			return _as_str(rows[0].get("name"))
	except Exception:
		pass

	rows = frappe.get_all(
		doctype,
		fields=["name"],
		order_by="name asc",
		limit_page_length=1,
	)
	if rows:
		return _as_str(rows[0].get("name"))

	return requested_name or fallback_name


def _resolve_customer_for_setup(kwargs: dict[str, Any]) -> tuple[str, str]:
	requested_customer_type = _as_str(kwargs.get("customer_type")) or "Company"
	requested_customer_group = _pick_non_group_link_value(
		"Customer Group", kwargs.get("customer_group"), "Commercial"
	)
	requested_territory = _pick_non_group_link_value("Territory", kwargs.get("territory"), "Australia")
	requested_email = _as_str(kwargs.get("email_id")) or None
	requested_mobile = _as_str(kwargs.get("mobile_no")) or None

	def _ensure_customer_defaults(doc: Any) -> None:
		changed = False

		if not _as_str(getattr(doc, "customer_type", "")):
			doc.customer_type = requested_customer_type
			changed = True

		resolved_group = _pick_non_group_link_value(
			"Customer Group",
			getattr(doc, "customer_group", None),
			requested_customer_group,
		)
		if resolved_group and _as_str(getattr(doc, "customer_group", "")) != resolved_group:
			doc.customer_group = resolved_group
			changed = True

		resolved_territory = _pick_non_group_link_value(
			"Territory",
			getattr(doc, "territory", None),
			requested_territory,
		)
		if resolved_territory and _as_str(getattr(doc, "territory", "")) != resolved_territory:
			doc.territory = resolved_territory
			changed = True

		if requested_email and not _as_str(getattr(doc, "email_id", "")):
			doc.email_id = requested_email
			changed = True

		if requested_mobile and not _as_str(getattr(doc, "mobile_no", "")):
			doc.mobile_no = requested_mobile
			changed = True

		if changed:
			doc.save(ignore_permissions=True)
			frappe.db.commit()

	customer = _as_str(kwargs.get("customer"))
	customer_name = _as_str(kwargs.get("customer_name")) or customer
	if customer and frappe.db.exists("Customer", customer):
		doc = frappe.get_doc("Customer", customer)
		_ensure_customer_defaults(doc)
		return doc.name, _as_str(doc.customer_name) or doc.name
	if customer_name:
		existing = frappe.get_all(
			"Customer",
			fields=["name", "customer_name"],
			filters={"customer_name": customer_name},
			limit_page_length=1,
		)
		if existing:
			row = existing[0]
			doc = frappe.get_doc("Customer", _as_str(row.get("name")))
			_ensure_customer_defaults(doc)
			return doc.name, _as_str(doc.customer_name) or doc.name
	created = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": customer_name or customer,
			"customer_type": requested_customer_type,
			"customer_group": requested_customer_group,
			"territory": requested_territory,
			"email_id": requested_email,
			"mobile_no": requested_mobile,
			"disabled": 1 if _as_bool(kwargs.get("disabled")) else 0,
		}
	)
	created.insert(ignore_permissions=True)
	frappe.db.commit()
	return created.name, _as_str(created.customer_name) or created.name


def _resolve_plan_for_setup(plan_name: str) -> dict[str, Any]:
	if not plan_name:
		return {}
	if not frappe.db.exists("DocType", "FL Subscription Plan"):
		return {}
	if not frappe.db.exists("FL Subscription Plan", plan_name):
		frappe.throw(f"Subscription plan '{plan_name}' was not found", frappe.ValidationError)
	return _local_get_plan(plan_name)


def _signup_request_summary(row: dict[str, Any]) -> dict[str, Any]:
	return {
		"name": _as_str(row.get("name")),
		"request_status": _as_str(row.get("request_status")) or "New",
		"submitted_on": _as_str(row.get("submitted_on")),
		"subscription_plan": _as_str(row.get("subscription_plan")),
		"plan_code": _as_str(row.get("plan_code")),
		"company_legal_name": _as_str(row.get("company_legal_name")),
		"company_trading_name": _as_str(row.get("company_trading_name")),
		"company_abn": _as_str(row.get("company_abn")),
		"company_address": _as_str(row.get("company_address")),
		"company_logo": _as_str(row.get("company_logo")),
		"current_system": _as_str(row.get("current_system")),
		"migration_scope": _as_str(row.get("migration_scope")),
		"import_data_required": 1 if _as_bool(row.get("import_data_required")) else 0,
		"migration_notes": _as_str(row.get("migration_notes")),
		"team_size": _as_int(row.get("team_size"), 0),
		"base_users_included": _as_int(row.get("base_users_included"), 0),
		"extra_users_requested": _as_int(row.get("extra_users_requested"), 0),
		"extra_user_rate": _as_float(row.get("extra_user_rate"), 0.0),
		"monthly_base_price": _as_float(row.get("monthly_base_price"), 0.0),
		"monthly_total_estimate": _as_float(row.get("monthly_total_estimate"), 0.0),
		"domain_option": _as_str(row.get("domain_option")),
		"requested_subdomain": _as_str(row.get("requested_subdomain")),
		"standard_site_host": _as_str(row.get("standard_site_host")),
		"standard_host_status": _as_str(row.get("standard_host_status")),
		"custom_domain": _as_str(row.get("custom_domain")),
		"requested_site_host": _as_str(row.get("requested_site_host")),
		"requested_host_status": _as_str(row.get("requested_host_status")),
		"availability_checked_on": _as_str(row.get("availability_checked_on")),
		"contact_name": _as_str(row.get("contact_name")),
		"contact_email": _as_str(row.get("contact_email")),
		"contact_phone": _as_str(row.get("contact_phone")),
		"accounts_email": _as_str(row.get("accounts_email")),
		"admin_first_name": _as_str(row.get("admin_first_name")),
		"admin_last_name": _as_str(row.get("admin_last_name")),
		"admin_username": _as_str(row.get("admin_username")),
		"admin_password_set": 1 if _as_str(row.get("admin_password")) else 0,
		"managed_website_option": 1 if _as_bool(row.get("managed_website_option")) else 0,
		"voip_option": 1 if _as_bool(row.get("voip_option")) else 0,
		"provisioning_readiness": _as_str(row.get("provisioning_readiness")),
		"activation_notes": _as_str(row.get("activation_notes")),
		"source_site": _as_str(row.get("source_site")),
		"source_url": _as_str(row.get("source_url")),
	}


def _sanitize_signup_subdomain(value: Any) -> str:
	raw = _as_str(value).lower()
	clean = "".join(ch if ch.isalnum() or ch == "-" else "-" for ch in raw)
	while "--" in clean:
		clean = clean.replace("--", "-")
	return clean.strip("-")


def _sanitize_signup_file_name(value: Any) -> str:
	name = os.path.basename(_as_str(value)) or "company-logo"
	clean = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in name)
	return clean.strip("-") or "company-logo"


def _extract_signup_logo_payload(kwargs: dict[str, Any]) -> dict[str, Any]:
	content = _as_str(kwargs.get("company_logo_content_base64"))
	filename = _sanitize_signup_file_name(
		kwargs.get("company_logo_filename") or kwargs.get("company_logo_name")
	)
	mime_type = _as_str(kwargs.get("company_logo_mime_type")) or "application/octet-stream"
	if content:
		return {
			"content_base64": content,
			"filename": filename,
			"mime_type": mime_type,
		}

	upload = getattr(getattr(frappe, "request", None), "files", None)
	file_obj = upload.get("company_logo_file") if upload else None
	if not file_obj:
		return {}
	file_bytes = file_obj.read()
	if not file_bytes:
		return {}
	return {
		"content_base64": base64.b64encode(file_bytes).decode("ascii"),
		"filename": _sanitize_signup_file_name(getattr(file_obj, "filename", "") or filename),
		"mime_type": _as_str(getattr(file_obj, "content_type", "")) or mime_type,
	}


def _attach_signup_logo(doc: Any, logo_payload: dict[str, Any]) -> None:
	content = _as_str((logo_payload or {}).get("content_base64"))
	if not content:
		return
	try:
		file_bytes = base64.b64decode(content)
	except Exception:
		frappe.throw("Invalid company logo upload", frappe.ValidationError)
	filename = _sanitize_signup_file_name((logo_payload or {}).get("filename") or "company-logo")
	saved = save_file(filename, file_bytes, doc.doctype, doc.name, is_private=0)
	file_url = ""
	if isinstance(saved, dict):
		file_url = _as_str(saved.get("file_url") or saved.get("name"))
	else:
		file_url = _as_str(getattr(saved, "file_url", "") or getattr(saved, "name", ""))
	if file_url:
		doc.company_logo = file_url
		doc.save(ignore_permissions=True)


def _local_signup_host_availability(site_host: Any, exclude_request_name: str = "") -> dict[str, Any]:
	host = _normalize_site_host(site_host)
	if not host:
		return {
			"site_host": "",
			"available": False,
			"status": "Invalid",
			"reason": "A valid site host is required.",
		}

	if _site_exists_on_disk(host):
		return {
			"site_host": host,
			"available": False,
			"status": "Provisioned",
			"reason": "This domain is already provisioned on our system.",
		}

	if frappe.db.exists("DocType", "FL Site Subscription"):
		subscription_name = frappe.db.get_value("FL Site Subscription", {"site_host": host}, "name")
		if subscription_name:
			return {
				"site_host": host,
				"available": False,
				"status": "Subscribed",
				"reason": f"This domain is already linked to subscription {subscription_name}.",
			}

	if frappe.db.exists("DocType", "FL Signup Request"):
		rows = frappe.get_all(
			"FL Signup Request",
			fields=["name", "request_status"],
			filters={"requested_site_host": host},
			order_by="modified desc",
			limit_page_length=5,
		)
		for row in rows:
			row_name = _as_str(row.get("name"))
			if exclude_request_name and row_name == exclude_request_name:
				continue
			status = _as_str(row.get("request_status")) or "New"
			if status.lower() == "rejected":
				continue
			return {
				"site_host": host,
				"available": False,
				"status": "Reserved",
				"reason": f"This domain is already attached to signup request {row_name}.",
				"request_name": row_name,
				"request_status": status,
			}

	return {
		"site_host": host,
		"available": True,
		"status": "Available",
		"reason": "This domain is available for a new FireTrack signup request.",
	}


def _local_signup_availability_payload(kwargs: dict[str, Any]) -> dict[str, Any]:
	domain_option = _as_str(kwargs.get("domain_option")) or "subdomain"
	requested_subdomain = _sanitize_signup_subdomain(
		kwargs.get("requested_subdomain") or kwargs.get("subdomain_name")
	)
	custom_domain = _normalize_site_host(kwargs.get("custom_domain"))
	if not requested_subdomain:
		frappe.throw("requested_subdomain is required", frappe.ValidationError)
	if domain_option == "custom" and not custom_domain:
		frappe.throw("custom_domain is required when custom domain is selected", frappe.ValidationError)

	standard_site_host = f"{requested_subdomain}.firetrackpro.com.au"
	requested_site_host = custom_domain if domain_option == "custom" and custom_domain else standard_site_host
	standard_check = _local_signup_host_availability(standard_site_host)
	requested_check = _local_signup_host_availability(requested_site_host)
	available = bool(standard_check.get("available")) and bool(requested_check.get("available"))
	return {
		"available": available,
		"domain_option": domain_option,
		"requested_subdomain": requested_subdomain,
		"standard_site_host": standard_site_host,
		"requested_site_host": requested_site_host,
		"standard_host_status": _as_str(standard_check.get("status")),
		"requested_host_status": _as_str(requested_check.get("status")),
		"standard_host_reason": _as_str(standard_check.get("reason")),
		"requested_host_reason": _as_str(requested_check.get("reason")),
		"checked_at": frappe.utils.now_datetime().isoformat(),
	}


def _auto_link_signup_customer_and_subscription(signup_doc: Any) -> dict[str, Any]:
	if not frappe.db.exists("DocType", "Customer") or not frappe.db.exists("DocType", "FL Site Subscription"):
		return {
			"linked_setup_created": 0,
			"linked_setup_message": "Customer or FL Site Subscription doctype is not installed.",
		}
	try:
		customer_name, customer_display_name = _resolve_customer_for_setup(
			{
				"customer_name": _as_str(getattr(signup_doc, "company_legal_name", "")),
				"customer_type": "Company",
				"customer_group": "Commercial",
				"territory": "Australia",
				"email_id": _as_str(getattr(signup_doc, "contact_email", "")),
				"mobile_no": _as_str(getattr(signup_doc, "contact_phone", "")),
			}
		)
		base_users = max(0, _as_int(getattr(signup_doc, "base_users_included", 0), 0))
		extra_users = max(0, _as_int(getattr(signup_doc, "extra_users_requested", 0), 0))
		allowed_users = max(
			0, _as_int(getattr(signup_doc, "team_size", base_users + extra_users), base_users + extra_users)
		)
		base_price = max(0.0, _as_float(getattr(signup_doc, "monthly_base_price", 0), 0.0))
		extra_user_rate = max(0.0, _as_float(getattr(signup_doc, "extra_user_rate", 0), 0.0))
		monthly_extra_users_amount = float(extra_users) * extra_user_rate
		monthly_total_amount = max(
			0.0,
			_as_float(
				getattr(signup_doc, "monthly_total_estimate", 0),
				base_price + monthly_extra_users_amount,
			),
		)
		subscription_row = _local_upsert_subscription_by_site(
			{
				"site_host": _as_str(getattr(signup_doc, "requested_site_host", "")),
				"site_alias": customer_display_name or customer_name,
				"customer": customer_name,
				"subscription_plan": _as_str(getattr(signup_doc, "subscription_plan", "")) or None,
				"subscription_status": "Trial",
				"base_users_included": base_users,
				"extra_users_purchased": extra_users,
				"allowed_users_total": allowed_users,
				"billing_cycle": "Monthly",
				"monthly_base_price": base_price,
				"monthly_extra_user_price": extra_user_rate,
				"monthly_extra_users_amount": monthly_extra_users_amount,
				"monthly_total_amount": monthly_total_amount,
				"subscription_reference": _as_str(getattr(signup_doc, "name", "")) or None,
				"notes": "Auto-linked from signup request {0}".format(
					_as_str(getattr(signup_doc, "name", ""))
				),
			}
		)
		return {
			"linked_setup_created": 1,
			"linked_customer": customer_name,
			"linked_customer_display_name": customer_display_name,
			"linked_subscription": _as_str(subscription_row.get("name")),
			"linked_setup_message": "Customer and subscription prepared for provisioning.",
		}
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), "FireLink Signup Auto Link Failed")
		return {
			"linked_setup_created": 0,
			"linked_setup_message": _as_str(exc) or "Auto link failed.",
		}


def _local_create_signup_request(
	kwargs: dict[str, Any], logo_payload: dict[str, Any] | None = None
) -> dict[str, Any]:
	if not frappe.db.exists("DocType", "FL Signup Request"):
		frappe.throw("FL Signup Request doctype is not installed", frappe.ValidationError)

	plan_name = _as_str(kwargs.get("subscription_plan"))
	plan = _resolve_plan_for_setup(plan_name)
	company_legal_name = _as_str(kwargs.get("company_legal_name"))
	contact_name = _as_str(kwargs.get("contact_name"))
	contact_email = _as_str(kwargs.get("contact_email"))
	domain_option = _as_str(kwargs.get("domain_option")) or "subdomain"
	requested_subdomain = _sanitize_signup_subdomain(
		kwargs.get("requested_subdomain") or kwargs.get("subdomain_name")
	)
	custom_domain = _normalize_site_host(kwargs.get("custom_domain"))
	if not company_legal_name:
		frappe.throw("company_legal_name is required", frappe.ValidationError)
	if not contact_name:
		frappe.throw("contact_name is required", frappe.ValidationError)
	if not contact_email:
		frappe.throw("contact_email is required", frappe.ValidationError)
	if not requested_subdomain:
		frappe.throw("requested_subdomain is required", frappe.ValidationError)
	if domain_option == "custom" and not custom_domain:
		frappe.throw("custom_domain is required when custom domain is selected", frappe.ValidationError)

	team_size = max(1, _as_int(kwargs.get("company_size") or kwargs.get("team_size"), 1))
	base_users = max(0, _as_int(plan.get("base_users_included"), 0))
	extra_user_rate = max(
		0.0,
		_as_float(kwargs.get("extra_user_rate"), _as_float(plan.get("extra_user_fee"), 0.0)),
	)
	extra_users_requested = max(
		0, _as_int(kwargs.get("extra_users_requested"), max(0, team_size - base_users))
	)
	monthly_base_price = max(
		0.0, _as_float(kwargs.get("monthly_base_price"), _as_float(plan.get("base_fee"), 0.0))
	)
	monthly_total_estimate = max(
		0.0,
		_as_float(
			kwargs.get("monthly_total_estimate"),
			monthly_base_price + float(extra_users_requested) * extra_user_rate,
		),
	)
	availability = _local_signup_availability_payload(
		{
			"domain_option": domain_option,
			"requested_subdomain": requested_subdomain,
			"custom_domain": custom_domain,
		}
	)
	if not _as_bool(availability.get("available")):
		frappe.throw(
			_as_str(availability.get("requested_host_reason"))
			or _as_str(availability.get("standard_host_reason"))
			or "The requested domain is not available.",
			frappe.ValidationError,
		)
	standard_site_host = _as_str(availability.get("standard_site_host"))
	requested_site_host = _as_str(availability.get("requested_site_host"))

	doc = frappe.get_doc(
		{
			"doctype": "FL Signup Request",
			"request_status": "Reviewed",
			"submitted_on": frappe.utils.now_datetime(),
			"subscription_plan": plan_name or None,
			"plan_code": _as_str(plan.get("plan_code")) or None,
			"company_legal_name": company_legal_name,
			"company_trading_name": _as_str(kwargs.get("company_trading_name")) or None,
			"company_abn": _as_str(kwargs.get("company_abn")) or None,
			"company_address": _as_str(kwargs.get("company_address")) or None,
			"current_system": _as_str(kwargs.get("current_system")) or None,
			"migration_scope": _as_str(kwargs.get("migration_scope")) or None,
			"import_data_required": 1 if _as_bool(kwargs.get("import_data_required")) else 0,
			"migration_notes": _as_str(kwargs.get("migration_notes")) or None,
			"team_size": team_size,
			"base_users_included": base_users,
			"extra_users_requested": extra_users_requested,
			"extra_user_rate": extra_user_rate,
			"monthly_base_price": monthly_base_price,
			"monthly_total_estimate": monthly_total_estimate,
			"domain_option": domain_option,
			"requested_subdomain": requested_subdomain,
			"standard_site_host": standard_site_host,
			"standard_host_status": _as_str(availability.get("standard_host_status")) or "Available",
			"custom_domain": custom_domain or None,
			"requested_site_host": requested_site_host,
			"requested_host_status": _as_str(availability.get("requested_host_status")) or "Available",
			"availability_checked_on": frappe.utils.now_datetime(),
			"contact_name": contact_name,
			"contact_email": contact_email,
			"contact_phone": _as_str(kwargs.get("contact_phone")) or None,
			"accounts_email": _as_str(kwargs.get("accounts_email")) or None,
			"admin_first_name": _as_str(kwargs.get("admin_first_name")) or None,
			"admin_last_name": _as_str(kwargs.get("admin_last_name")) or None,
			"admin_username": _as_str(kwargs.get("admin_username")) or "Administrator",
			"admin_password": _as_str(kwargs.get("admin_password")) or None,
			"managed_website_option": 1 if _as_bool(kwargs.get("managed_website_option")) else 0,
			"voip_option": 1 if _as_bool(kwargs.get("voip_option")) else 0,
			"provisioning_readiness": "Ready for Manual Provisioning",
			"activation_notes": _as_str(kwargs.get("activation_notes")) or None,
			"source_site": _as_str(kwargs.get("source_site"))
			or _as_str(getattr(frappe.local, "site", ""))
			or None,
			"source_url": _as_str(kwargs.get("source_url")) or None,
		}
	)
	doc.insert(ignore_permissions=True)
	_attach_signup_logo(doc, logo_payload or {})
	auto_link = _auto_link_signup_customer_and_subscription(doc)
	if _as_bool(auto_link.get("linked_setup_created")):
		doc.provisioning_readiness = "Customer + Subscription Ready"
		doc.save(ignore_permissions=True)
	frappe.db.commit()
	result = _signup_request_summary(doc.as_dict())
	result.update(auto_link)
	return result


def _default_company() -> str:
	return _as_str(frappe.defaults.get_global_default("company"))


def _build_setup_items(
	base_item_code: str,
	extra_item_code: str,
	base_price: float,
	extra_user_price: float,
	extra_users: int,
) -> list[dict[str, Any]]:
	items: list[dict[str, Any]] = []
	has_base_item = bool(_as_str(base_item_code))
	has_extra_item = bool(_as_str(extra_item_code))

	# Allow explicit base item selection even when base price is 0 (for $0 recurring templates).
	if has_base_item:
		items.append({"item_code": base_item_code, "qty": 1, "rate": max(0.0, base_price)})
	elif base_price > 0:
		frappe.throw(
			"base_item_code is required when monthly base price is above zero.",
			frappe.ValidationError,
		)

	if extra_users > 0:
		if has_extra_item:
			items.append(
				{
					"item_code": extra_item_code,
					"qty": max(0, extra_users),
					"rate": max(0.0, extra_user_price),
				}
			)
		elif extra_user_price > 0:
			frappe.throw(
				"extra_user_item_code is required when extra user monthly billing is above zero.",
				frappe.ValidationError,
			)

	if not items:
		frappe.throw(
			"At least one recurring billing item is required. Set a base price above $0 or choose a base subscription item code.",
			frappe.ValidationError,
		)
	return items


def _create_quotation_for_setup(
	customer_name: str,
	customer_display_name: str,
	company: str,
	posting_date: str,
	items: list[dict[str, Any]],
	site_host: str,
	billing_cycle: str,
	base_users: int,
	extra_users: int,
	monthly_total: float,
) -> str:
	doc = frappe.get_doc(
		{
			"doctype": "Quotation",
			"quotation_to": "Customer",
			"party_name": customer_name,
			"customer_name": customer_display_name or customer_name,
			"company": company,
			"transaction_date": posting_date,
			"valid_till": posting_date,
			"order_type": "Sales",
			"items": items,
			"remarks": "\n".join(
				[
					f"FireLink site: {site_host}",
					f"Billing cycle: {billing_cycle}",
					f"Included users: {base_users}",
					f"Extra users: {extra_users}",
					f"Monthly total: {monthly_total:.2f}",
				]
			),
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc.name


def _create_sales_invoice_for_setup(
	customer_name: str,
	company: str,
	posting_date: str,
	items: list[dict[str, Any]],
	site_host: str,
	billing_cycle: str,
	base_users: int,
	extra_users: int,
	monthly_total: float,
) -> str:
	doc = frappe.get_doc(
		{
			"doctype": "Sales Invoice",
			"customer": customer_name,
			"company": company,
			"posting_date": posting_date,
			"due_date": posting_date,
			"items": items,
			"remarks": "\n".join(
				[
					f"FireLink site: {site_host}",
					f"Billing cycle: {billing_cycle}",
					f"Included users: {base_users}",
					f"Extra users: {extra_users}",
					f"Monthly total: {monthly_total:.2f}",
				]
			),
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc.name


def _create_auto_repeat_for_setup(invoice_name: str, billing_cycle: str, start_date: str) -> str:
	doc = frappe.get_doc(
		{
			"doctype": "Auto Repeat",
			"reference_doctype": "Sales Invoice",
			"reference_document": invoice_name,
			"frequency": _billing_cycle_to_frequency(billing_cycle),
			"start_date": start_date,
			"disabled": 0,
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc.name


def _upsert_subscription_for_setup(payload: dict[str, Any]) -> dict[str, Any]:
	if _is_firelink_local_site():
		return _local_upsert_subscription_by_site(payload)
	return (
		_firelink_remote_bridge_call(
			"/api/method/firtrackpro.api.integrations.firelink_admin_subscriptions_bridge",
			_remote_bridge_payload({"action": "upsert_by_site", **payload}),
		).get("row")
		or {}
	)


@frappe.whitelist(methods=["POST"])
def firelink_admin_list_plans(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	if _is_firelink_local_site():
		return {"rows": _local_list_plans()}
	return _firelink_remote_bridge_call(
		"/api/method/firtrackpro.api.integrations.firelink_admin_plans_bridge",
		_remote_bridge_payload({"action": "list"}),
	)


@frappe.whitelist(methods=["POST"])
def firelink_admin_get_plan(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	name = _as_str(kwargs.get("name"))
	if not name:
		frappe.throw("name is required", frappe.ValidationError)
	if _is_firelink_local_site():
		return {"row": _local_get_plan(name)}
	return _firelink_remote_bridge_call(
		"/api/method/firtrackpro.api.integrations.firelink_admin_plans_bridge",
		_remote_bridge_payload({"action": "get", "name": name}),
	)


@frappe.whitelist(methods=["POST"])
def firelink_admin_create_plan(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	if _is_firelink_local_site():
		return {"row": _local_create_plan(kwargs)}
	return _firelink_remote_bridge_call(
		"/api/method/firtrackpro.api.integrations.firelink_admin_plans_bridge",
		_remote_bridge_payload({"action": "create", **kwargs}),
	)


@frappe.whitelist(methods=["POST"])
def firelink_admin_update_plan(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	if _is_firelink_local_site():
		return {"row": _local_update_plan(kwargs)}
	return _firelink_remote_bridge_call(
		"/api/method/firtrackpro.api.integrations.firelink_admin_plans_bridge",
		_remote_bridge_payload({"action": "update", **kwargs}),
	)


@frappe.whitelist(methods=["POST"])
def firelink_admin_seed_default_plans(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	defaults = [
		{
			"plan_name": "Starter",
			"plan_code": "STARTER",
			"description": "$295/month includes 5 users, +$30 per extra user",
			"billing_cycle": "Monthly",
			"base_fee": 295,
			"base_users_included": 5,
			"extra_user_fee": 30,
			"default_extra_users": 0,
			"sort_order": 10,
			"is_active": 1,
		},
		{
			"plan_name": "Growth",
			"plan_code": "GROWTH",
			"description": "$595/month includes 20 users, lower per-user pricing",
			"billing_cycle": "Monthly",
			"base_fee": 595,
			"base_users_included": 20,
			"extra_user_fee": 25,
			"default_extra_users": 0,
			"sort_order": 20,
			"is_active": 1,
		},
		{
			"plan_name": "Pro",
			"plan_code": "PRO",
			"description": "$995/month includes 50 users, best value",
			"billing_cycle": "Monthly",
			"base_fee": 995,
			"base_users_included": 50,
			"extra_user_fee": 20,
			"default_extra_users": 0,
			"sort_order": 30,
			"is_active": 1,
		},
	]
	rows: list[dict[str, Any]] = []
	for plan in defaults:
		rows.append(_local_upsert_plan_by_code(plan))
	return {"rows": rows}


@frappe.whitelist(methods=["POST"])
def firelink_admin_setup_subscription(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	site_host = _normalize_site_host(kwargs.get("site_host"))
	if not site_host:
		frappe.throw("site_host is required", frappe.ValidationError)

	customer_name, customer_display_name = _resolve_customer_for_setup(kwargs)
	plan_name = _as_str(kwargs.get("subscription_plan"))
	plan = _resolve_plan_for_setup(plan_name)

	billing_cycle = _as_str(kwargs.get("billing_cycle")) or _as_str(plan.get("billing_cycle")) or "Monthly"
	base_users = _as_int(
		kwargs.get("base_users_included"),
		_as_int(plan.get("base_users_included"), 0),
	)
	extra_users = _as_int(
		kwargs.get("extra_users_purchased"),
		_as_int(plan.get("default_extra_users"), 0),
	)
	allowed_users = _as_int(
		kwargs.get("allowed_users_total"),
		max(0, base_users + extra_users),
	)
	base_price = _as_float(kwargs.get("base_price"), _as_float(plan.get("base_fee"), 0.0))
	extra_user_price = _as_float(kwargs.get("extra_user_price"), _as_float(plan.get("extra_user_fee"), 0.0))
	base_item_code = _as_str(kwargs.get("base_item_code")) or _as_str(plan.get("base_item_code"))
	extra_user_item_code = _as_str(kwargs.get("extra_user_item_code")) or _as_str(
		plan.get("extra_user_item_code")
	)
	monthly_extra_users_amount = max(0.0, float(extra_users) * max(0.0, extra_user_price))
	monthly_total = max(0.0, base_price) + monthly_extra_users_amount

	company = _as_str(kwargs.get("company")) or _default_company()
	if not company:
		frappe.throw("company is required", frappe.ValidationError)
	posting_date = (
		_as_str(kwargs.get("invoice_start_date") or kwargs.get("posting_date")) or frappe.utils.nowdate()
	)
	next_invoice_date = _as_str(kwargs.get("next_invoice_date")) or posting_date

	items = _build_setup_items(
		base_item_code=base_item_code,
		extra_item_code=extra_user_item_code,
		base_price=max(0.0, base_price),
		extra_user_price=max(0.0, extra_user_price),
		extra_users=max(0, extra_users),
	)
	quotation_name = _create_quotation_for_setup(
		customer_name=customer_name,
		customer_display_name=customer_display_name,
		company=company,
		posting_date=posting_date,
		items=items,
		site_host=site_host,
		billing_cycle=billing_cycle,
		base_users=max(0, base_users),
		extra_users=max(0, extra_users),
		monthly_total=monthly_total,
	)
	invoice_name = _create_sales_invoice_for_setup(
		customer_name=customer_name,
		company=company,
		posting_date=posting_date,
		items=items,
		site_host=site_host,
		billing_cycle=billing_cycle,
		base_users=max(0, base_users),
		extra_users=max(0, extra_users),
		monthly_total=monthly_total,
	)
	auto_repeat_name = _create_auto_repeat_for_setup(
		invoice_name=invoice_name,
		billing_cycle=billing_cycle,
		start_date=posting_date,
	)

	subscription_notes = _as_str(kwargs.get("notes"))
	if not subscription_notes:
		subscription_notes = "\n".join(
			[
				f"Plan: {plan_name or 'Custom'}",
				f"Quotation: {quotation_name}",
				f"Sales Invoice: {invoice_name}",
				f"Auto Repeat: {auto_repeat_name}",
				f"Billing cycle: {billing_cycle}",
				f"Included users: {max(0, base_users)}",
				f"Extra users: {max(0, extra_users)}",
			]
		)

	sub_payload = {
		"site_host": site_host,
		"site_alias": _as_str(kwargs.get("site_alias")) or customer_display_name,
		"customer": customer_name,
		"subscription_plan": plan_name or None,
		"subscription_status": _as_str(kwargs.get("subscription_status")) or "Active",
		"base_users_included": max(0, base_users),
		"extra_users_purchased": max(0, extra_users),
		"allowed_users_total": max(0, allowed_users),
		"billing_cycle": billing_cycle,
		"next_invoice_date": next_invoice_date,
		"subscription_reference": _as_str(kwargs.get("subscription_reference")) or invoice_name,
		"quotation_reference": quotation_name,
		"sales_invoice_reference": invoice_name,
		"auto_repeat_reference": auto_repeat_name,
		"base_item_code": base_item_code or None,
		"extra_user_item_code": extra_user_item_code or None,
		"monthly_base_price": max(0.0, base_price),
		"monthly_extra_user_price": max(0.0, extra_user_price),
		"monthly_extra_users_amount": monthly_extra_users_amount,
		"monthly_total_amount": monthly_total,
		"notes": subscription_notes,
	}
	subscription_row = _upsert_subscription_for_setup(sub_payload)

	return {
		"customer": customer_name,
		"customer_display_name": customer_display_name,
		"quotation": quotation_name,
		"sales_invoice": invoice_name,
		"auto_repeat": auto_repeat_name,
		"subscription": subscription_row,
	}


@frappe.whitelist(methods=["POST"])
def firelink_admin_list_subscriptions(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	if _is_firelink_local_site():
		return {"rows": _local_list_subscriptions()}
	return _firelink_remote_bridge_call(
		"/api/method/firtrackpro.api.integrations.firelink_admin_subscriptions_bridge",
		_remote_bridge_payload({"action": "list"}),
	)


@frappe.whitelist(methods=["POST"])
def firelink_admin_get_subscription(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	name = _as_str(kwargs.get("name"))
	if not name:
		frappe.throw("name is required", frappe.ValidationError)
	if _is_firelink_local_site():
		return {"row": _local_get_subscription(name)}
	return _firelink_remote_bridge_call(
		"/api/method/firtrackpro.api.integrations.firelink_admin_subscriptions_bridge",
		_remote_bridge_payload({"action": "get", "name": name}),
	)


@frappe.whitelist(methods=["POST"])
def firelink_admin_create_subscription(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	if _is_firelink_local_site():
		return {"row": _local_create_subscription(kwargs)}
	return _firelink_remote_bridge_call(
		"/api/method/firtrackpro.api.integrations.firelink_admin_subscriptions_bridge",
		_remote_bridge_payload({"action": "create", **kwargs}),
	)


@frappe.whitelist(methods=["POST"])
def firelink_admin_update_subscription(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	if _is_firelink_local_site():
		return {"row": _local_update_subscription(kwargs)}
	return _firelink_remote_bridge_call(
		"/api/method/firtrackpro.api.integrations.firelink_admin_subscriptions_bridge",
		_remote_bridge_payload({"action": "update", **kwargs}),
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def firelink_public_submit_signup_request(**kwargs):
	logo_payload = _extract_signup_logo_payload(kwargs)
	if _is_firelink_local_site():
		return {"row": _local_create_signup_request(kwargs, logo_payload)}
	return _firelink_remote_bridge_call(
		"/api/method/firtrackpro.api.integrations.firelink_public_signup_request_bridge",
		_remote_bridge_payload({**kwargs, **logo_payload}),
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def firelink_public_signup_request_bridge(**kwargs):
	if not _is_valid_bridge_call():
		frappe.throw("Bridge token or approved firetrackpro origin is required", frappe.PermissionError)
	logo_payload = _extract_signup_logo_payload(kwargs)
	return {"row": _local_create_signup_request(kwargs, logo_payload)}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def firelink_public_check_signup_availability(**kwargs):
	if _is_firelink_local_site():
		return {"row": _local_signup_availability_payload(kwargs)}
	return _firelink_remote_bridge_call(
		"/api/method/firtrackpro.api.integrations.firelink_public_signup_availability_bridge",
		_remote_bridge_payload(kwargs),
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def firelink_public_signup_availability_bridge(**kwargs):
	if not _is_valid_bridge_call():
		frappe.throw("Bridge token or approved firetrackpro origin is required", frappe.PermissionError)
	return {"row": _local_signup_availability_payload(kwargs)}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def firelink_admin_plans_bridge(**kwargs):
	if not _is_valid_bridge_call():
		frappe.throw("Bridge token or approved firetrackpro origin is required", frappe.PermissionError)
	action = _as_str(kwargs.get("action")).lower()
	if action == "list":
		return {"rows": _local_list_plans()}
	if action == "get":
		return {"row": _local_get_plan(_as_str(kwargs.get("name")))}
	if action == "create":
		return {"row": _local_create_plan(kwargs)}
	if action == "update":
		return {"row": _local_update_plan(kwargs)}
	if action == "upsert_by_code":
		return {"row": _local_upsert_plan_by_code(kwargs)}
	frappe.throw("Invalid action", frappe.ValidationError)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def firelink_admin_subscriptions_bridge(**kwargs):
	if not _is_valid_bridge_call():
		frappe.throw("Bridge token or approved firetrackpro origin is required", frappe.PermissionError)
	action = _as_str(kwargs.get("action")).lower()
	if action == "list":
		return {"rows": _local_list_subscriptions()}
	if action == "get":
		return {"row": _local_get_subscription(_as_str(kwargs.get("name")))}
	if action == "quota":
		site_host = (
			_as_str(kwargs.get("site_host")) or _as_str(kwargs.get("host")) or _as_str(kwargs.get("site"))
		)
		return {"quota": _local_subscription_quota(site_host)}
	if action == "create":
		return {"row": _local_create_subscription(kwargs)}
	if action == "update":
		return {"row": _local_update_subscription(kwargs)}
	if action == "find_by_site":
		return {"row": _local_find_subscription_by_site(_as_str(kwargs.get("site_host")))}
	if action == "upsert_by_site":
		return {"row": _local_upsert_subscription_by_site(kwargs)}
	frappe.throw("Invalid action", frappe.ValidationError)


@frappe.whitelist(methods=["POST"])
def firelink_admin_list_recurring_billing(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	if _is_firelink_local_site():
		return {"rows": _local_list_recurring()}
	return _firelink_remote_bridge_call(
		"/api/method/firtrackpro.api.integrations.firelink_admin_recurring_billing_bridge",
		_remote_bridge_payload({"action": "list"}),
	)


@frappe.whitelist(methods=["POST"])
def firelink_admin_get_recurring_billing(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	name = _as_str(kwargs.get("name"))
	if not name:
		frappe.throw("name is required", frappe.ValidationError)
	if _is_firelink_local_site():
		return {"row": _local_get_recurring(name)}
	return _firelink_remote_bridge_call(
		"/api/method/firtrackpro.api.integrations.firelink_admin_recurring_billing_bridge",
		_remote_bridge_payload({"action": "get", "name": name}),
	)


@frappe.whitelist(methods=["POST"])
def firelink_admin_create_recurring_billing(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	if _is_firelink_local_site():
		return {"row": _local_create_recurring(kwargs)}
	return _firelink_remote_bridge_call(
		"/api/method/firtrackpro.api.integrations.firelink_admin_recurring_billing_bridge",
		_remote_bridge_payload({"action": "create", **kwargs}),
	)


@frappe.whitelist(methods=["POST"])
def firelink_admin_update_recurring_billing(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	if _is_firelink_local_site():
		return {"row": _local_update_recurring(kwargs)}
	return _firelink_remote_bridge_call(
		"/api/method/firtrackpro.api.integrations.firelink_admin_recurring_billing_bridge",
		_remote_bridge_payload({"action": "update", **kwargs}),
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def firelink_admin_recurring_billing_bridge(**kwargs):
	if not _is_valid_bridge_call():
		frappe.throw("Bridge token or approved firetrackpro origin is required", frappe.PermissionError)
	action = _as_str(kwargs.get("action")).lower()
	if action == "list":
		return {"rows": _local_list_recurring()}
	if action == "get":
		return {"row": _local_get_recurring(_as_str(kwargs.get("name")))}
	if action == "create":
		return {"row": _local_create_recurring(kwargs)}
	if action == "update":
		return {"row": _local_update_recurring(kwargs)}
	frappe.throw("Invalid action", frappe.ValidationError)


def _normalize_site_host(raw: Any) -> str:
	host = _as_str(raw).lower()
	host = host.replace("http://", "").replace("https://", "")
	host = host.split("/")[0].strip()
	return host


def _sites_root_path() -> str:
	current_site_path = frappe.get_site_path()
	return os.path.dirname(current_site_path)


def _site_paths_for_host(site_host: str) -> tuple[str, str]:
	safe_host = _normalize_site_host(site_host)
	site_dir = os.path.join(_sites_root_path(), safe_host)
	config_path = os.path.join(site_dir, "site_config.json")
	return site_dir, config_path


def _site_exists_on_disk(site_host: str) -> bool:
	site_dir, config_path = _site_paths_for_host(site_host)
	return os.path.isdir(site_dir) and os.path.isfile(config_path)


def _local_site_status_payload(site_host: str) -> dict[str, Any]:
	host = _normalize_site_host(site_host)
	if not host:
		frappe.throw("site_host is required", frappe.ValidationError)

	row = None
	if frappe.db.exists("DocType", "FL Site Subscription"):
		row = frappe.db.get_value(
			"FL Site Subscription",
			{"site_host": host},
			["name", "customer"],
			as_dict=True,
		)

	status_run = _run_site_status_command(
		site_host=host,
		namespace=_as_str(getattr(frappe.local, "form_dict", {}).get("namespace")),
		release_name=_as_str(getattr(frappe.local, "form_dict", {}).get("release_name")),
		values_path=_as_str(getattr(frappe.local, "form_dict", {}).get("values_path")),
	)
	if status_run.get("configured"):
		exists = 1 if _as_bool(status_run.get("exists")) else 0
		status = "success" if exists else "missing"
		message = _as_str(status_run.get("message")) or (
			f"Site {host} exists in k8s." if exists else f"Site {host} is not provisioned in k8s yet."
		)
		out = {
			"status": status,
			"message": message,
			"site_host": host,
			"exists_in_k8s": exists,
			"provisioned": exists,
			"checked_at": datetime.now(timezone.utc).isoformat(),
		}
		details = _as_str(status_run.get("details"))
		if details:
			out["details"] = details
		if row:
			out["subscription"] = {
				"name": _as_str(row.get("name")),
				"customer": _as_str(row.get("customer")),
			}
		return out

	exists = _site_exists_on_disk(host)
	if exists:
		status = "success"
		message = f"Site {host} exists on this cluster (sites directory + site_config.json found)."
	else:
		status = "missing"
		message = (
			f"Site {host} is not provisioned on this cluster yet (site folder/site_config.json not found)."
		)

	out = {
		"status": status,
		"message": message,
		"site_host": host,
		"exists_in_k8s": 1 if exists else 0,
		"provisioned": 1 if exists else 0,
		"checked_at": datetime.now(timezone.utc).isoformat(),
	}
	if row:
		out["subscription"] = {
			"name": _as_str(row.get("name")),
			"customer": _as_str(row.get("customer")),
		}
	return out


def _site_status_command_template() -> str:
	return _site_conf_value(*FIRELINK_SITE_STATUS_COMMAND_CANDIDATES)


def _run_site_status_command(**kwargs) -> dict[str, Any]:
	template = _site_status_command_template()
	host = _normalize_site_host(kwargs.get("site_host"))
	if not template:
		return {"configured": False}
	if not host:
		return {"configured": True, "ok": False, "exists": False, "message": "site_host is required"}

	payload = {
		"site_host": shlex.quote(host),
		"namespace": shlex.quote(_as_str(kwargs.get("namespace"))),
		"release_name": shlex.quote(_as_str(kwargs.get("release_name"))),
		"values_path": shlex.quote(_as_str(kwargs.get("values_path"))),
		"image_tag": shlex.quote(_as_str(kwargs.get("image_tag"))),
	}

	try:
		command = template.format(**payload)
	except Exception as exc:
		return {
			"configured": True,
			"ok": False,
			"exists": False,
			"message": f"Status command template is invalid: {exc}",
		}

	try:
		res = subprocess.run(
			command,
			shell=True,
			check=False,
			text=True,
			capture_output=True,
			timeout=600,
			cwd=_sites_root_path(),
		)
	except Exception as exc:
		return {
			"configured": True,
			"ok": False,
			"exists": False,
			"message": f"Status command failed to start: {exc}",
		}

	output = ((res.stdout or "") + "\n" + (res.stderr or "")).strip()
	if len(output) > 1200:
		output = output[-1200:]
	text_out = output.lower()
	exists = "status_ok" in text_out
	if "status_missing" in text_out:
		exists = False

	if res.returncode != 0 and "status_ok" not in text_out and "status_missing" not in text_out:
		return {
			"configured": True,
			"ok": False,
			"exists": False,
			"message": f"Status command failed with exit code {res.returncode}.",
			"details": output,
		}

	return {
		"configured": True,
		"ok": True,
		"exists": bool(exists),
		"message": "Site exists in k8s." if exists else "Site is not provisioned in k8s yet.",
		"details": output,
	}


def _provision_command_template() -> str:
	return _site_conf_value(*FIRELINK_PROVISION_COMMAND_CANDIDATES)


def _domain_provision_command_template() -> str:
	return _site_conf_value(*FIRELINK_DOMAIN_PROVISION_COMMAND_CANDIDATES)


def _run_provision_command(**kwargs) -> dict[str, Any]:
	template = _provision_command_template()
	if not template:
		return {
			"ok": False,
			"message": (
				"Provision command is not configured. Set firelink_provision_command in site_config.json "
				"with placeholders {site_host}, {admin_password}, {namespace}, {release_name}, {values_path}, {image_tag}."
			),
		}

	payload = {
		"site_host": shlex.quote(_normalize_site_host(kwargs.get("site_host"))),
		"admin_password": shlex.quote(_as_str(kwargs.get("admin_password"))),
		"namespace": shlex.quote(_as_str(kwargs.get("namespace"))),
		"release_name": shlex.quote(_as_str(kwargs.get("release_name"))),
		"values_path": shlex.quote(_as_str(kwargs.get("values_path"))),
		"image_tag": shlex.quote(_as_str(kwargs.get("image_tag"))),
	}

	try:
		command = template.format(**payload)
	except Exception as exc:
		return {"ok": False, "message": f"Provision command template is invalid: {exc}"}

	try:
		res = subprocess.run(
			command,
			shell=True,
			check=False,
			text=True,
			capture_output=True,
			timeout=2400,
			cwd=_sites_root_path(),
		)
	except Exception as exc:
		return {"ok": False, "message": f"Provision command failed to start: {exc}"}

	output = ((res.stdout or "") + "\n" + (res.stderr or "")).strip()
	redacted_pw = _as_str(kwargs.get("admin_password"))
	if redacted_pw:
		output = output.replace(redacted_pw, "******")
	if len(output) > 1200:
		output = output[-1200:]

	if res.returncode != 0:
		return {
			"ok": False,
			"message": f"Provision command failed with exit code {res.returncode}.",
			"details": output,
		}
	return {
		"ok": True,
		"message": "Provision command completed.",
		"details": output,
	}


def _run_domain_provision_command(**kwargs) -> dict[str, Any]:
	template = _domain_provision_command_template()
	if not template:
		return {
			"ok": False,
			"message": (
				"Domain command is not configured. Set firelink_domain_provision_command in site_config.json "
				"with placeholders {site_host}, {admin_password}, {namespace}, {release_name}, {values_path}, {image_tag}."
			),
		}

	payload = {
		"site_host": shlex.quote(_normalize_site_host(kwargs.get("site_host"))),
		"admin_password": shlex.quote(_as_str(kwargs.get("admin_password"))),
		"namespace": shlex.quote(_as_str(kwargs.get("namespace"))),
		"release_name": shlex.quote(_as_str(kwargs.get("release_name"))),
		"values_path": shlex.quote(_as_str(kwargs.get("values_path"))),
		"image_tag": shlex.quote(_as_str(kwargs.get("image_tag"))),
	}

	try:
		command = template.format(**payload)
	except Exception as exc:
		return {"ok": False, "message": f"Domain command template is invalid: {exc}"}

	try:
		res = subprocess.run(
			command,
			shell=True,
			check=False,
			text=True,
			capture_output=True,
			timeout=1800,
			cwd=_sites_root_path(),
		)
	except Exception as exc:
		return {"ok": False, "message": f"Domain command failed to start: {exc}"}

	output = ((res.stdout or "") + "\n" + (res.stderr or "")).strip()
	redacted_pw = _as_str(kwargs.get("admin_password"))
	if redacted_pw:
		output = output.replace(redacted_pw, "******")
	if len(output) > 1200:
		output = output[-1200:]

	if res.returncode != 0:
		return {
			"ok": False,
			"message": f"Domain command failed with exit code {res.returncode}.",
			"details": output,
		}
	return {
		"ok": True,
		"message": "Domain command completed.",
		"details": output,
	}


def _attach_domain_result(result: dict[str, Any], **kwargs) -> dict[str, Any]:
	if not _as_bool(kwargs.get("configure_domain")):
		result["domain_status"] = "skipped"
		result["domain_message"] = "Domain setup not requested."
		return result
	domain_run = _run_domain_provision_command(**kwargs)
	result["domain_status"] = "success" if _as_bool(domain_run.get("ok")) else "failed"
	result["domain_message"] = _as_str(domain_run.get("message"))
	details = _as_str(domain_run.get("details"))
	if details:
		result["domain_details"] = details
	return result


@frappe.whitelist(methods=["POST"])
def firelink_admin_site_status(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	host = _normalize_site_host(kwargs.get("site_host"))
	if not host:
		frappe.throw("site_host is required", frappe.ValidationError)
	if _is_firelink_local_site():
		return _local_site_status_payload(host)
	return _firelink_remote_bridge_call(
		"/api/method/firtrackpro.api.integrations.firelink_admin_site_status_bridge",
		_remote_bridge_payload({"site_host": host}),
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def firelink_admin_site_status_bridge(**kwargs):
	if not _is_valid_bridge_call():
		frappe.throw("Bridge token or approved firetrackpro origin is required", frappe.PermissionError)
	host = _normalize_site_host(kwargs.get("site_host"))
	if not host:
		frappe.throw("site_host is required", frappe.ValidationError)
	return _local_site_status_payload(host)


@frappe.whitelist(methods=["POST"])
def firelink_admin_provision_site(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	host = _normalize_site_host(kwargs.get("site_host"))
	if not host:
		frappe.throw("site_host is required", frappe.ValidationError)
	if _is_firelink_local_site():
		before = _local_site_status_payload(host)
		if _as_bool(before.get("exists_in_k8s")):
			return _attach_domain_result(
				{
					**before,
					"status": "success",
					"message": f"Site {host} is already provisioned.",
				},
				**kwargs,
			)

		run = _run_provision_command(
			site_host=host,
			admin_password=kwargs.get("admin_password"),
			namespace=kwargs.get("namespace"),
			release_name=kwargs.get("release_name"),
			values_path=kwargs.get("values_path"),
			image_tag=kwargs.get("image_tag"),
		)
		after = _local_site_status_payload(host)
		if _as_bool(after.get("exists_in_k8s")):
			return _attach_domain_result(
				{
					**after,
					"status": "success",
					"message": _as_str(run.get("message")) or f"Site {host} provisioned.",
					"details": _as_str(run.get("details")),
				},
				**kwargs,
			)
		return _attach_domain_result(
			{
				**after,
				"status": "not_ready",
				"message": _as_str(run.get("message")) or f"Provisioning for {host} did not complete.",
				"details": _as_str(run.get("details")),
			},
			**kwargs,
		)

	return _firelink_remote_bridge_call(
		"/api/method/firtrackpro.api.integrations.firelink_admin_provision_site_bridge",
		_remote_bridge_payload(
			{
				"site_host": host,
				"admin_password": kwargs.get("admin_password"),
				"namespace": kwargs.get("namespace"),
				"release_name": kwargs.get("release_name"),
				"values_path": kwargs.get("values_path"),
				"image_tag": kwargs.get("image_tag"),
				"configure_domain": kwargs.get("configure_domain"),
			}
		),
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def firelink_admin_provision_site_bridge(**kwargs):
	if not _is_valid_bridge_call():
		frappe.throw("Bridge token or approved firetrackpro origin is required", frappe.PermissionError)
	host = _normalize_site_host(kwargs.get("site_host"))
	if not host:
		frappe.throw("site_host is required", frappe.ValidationError)
	before = _local_site_status_payload(host)
	if _as_bool(before.get("exists_in_k8s")):
		return _attach_domain_result(
			{
				**before,
				"status": "success",
				"message": f"Site {host} is already provisioned.",
			},
			**kwargs,
		)

	run = _run_provision_command(
		site_host=host,
		admin_password=kwargs.get("admin_password"),
		namespace=kwargs.get("namespace"),
		release_name=kwargs.get("release_name"),
		values_path=kwargs.get("values_path"),
		image_tag=kwargs.get("image_tag"),
	)
	after = _local_site_status_payload(host)
	if _as_bool(after.get("exists_in_k8s")):
		return _attach_domain_result(
			{
				**after,
				"status": "success",
				"message": _as_str(run.get("message")) or f"Site {host} provisioned.",
				"details": _as_str(run.get("details")),
			},
			**kwargs,
		)
	return _attach_domain_result(
		{
			**after,
			"status": "not_ready",
			"message": _as_str(run.get("message")) or f"Provisioning for {host} did not complete.",
			"details": _as_str(run.get("details")),
		},
		**kwargs,
	)


def _upsert_fl_property_local(payload: dict[str, Any]) -> dict[str, Any]:
	address_id = _as_str(payload.get("firelink_address_id")) or _as_str(payload.get("address_id"))
	if not address_id:
		frappe.throw("firelink_address_id is required", frappe.ValidationError)
	property_id = (
		_as_str(payload.get("firelink_property_id"))
		or _find_fl_property_by_address_id(address_id)
		or address_id
	)
	display_name = (
		_as_str(payload.get("property_display_name")) or _as_str(payload.get("address_title")) or address_id
	)
	address_json = {
		"address_id": address_id,
		"address_title": _as_str(payload.get("address_title")),
		"address_line1": _as_str(payload.get("address_line1")),
		"address_line2": _as_str(payload.get("address_line2")),
		"city": _as_str(payload.get("city")),
		"state": _as_str(payload.get("state")),
		"pincode": _as_str(payload.get("pincode")),
		"country": _as_str(payload.get("country")) or "Australia",
	}
	lat = _as_float(payload.get("property_lat"), 0.0)
	lng = _as_float(payload.get("property_lng"), 0.0)

	if frappe.db.exists("FL Property", property_id):
		doc = frappe.get_doc("FL Property", property_id)
		doc.property_display_name = display_name
		doc.property_address_json = json.dumps(address_json, separators=(",", ":"))
		doc.property_lat = lat
		doc.property_lng = lng
		doc.save(ignore_permissions=True)
		created = False
	else:
		doc = frappe.get_doc(
			{
				"doctype": "FL Property",
				"name": property_id,
				"property_display_name": display_name,
				"property_address_json": json.dumps(address_json, separators=(",", ":")),
				"property_lat": lat,
				"property_lng": lng,
			}
		)
		doc.insert(ignore_permissions=True)
		created = True
	firelink_property_id = _as_str(doc.name)
	ft_property_id = _upsert_ft_property_local(
		{
			"firelink_property_id": firelink_property_id,
			"firelink_address_id": address_id,
			"property_display_name": display_name,
			"property_lat": lat,
			"property_lng": lng,
			"address_line1": _as_str(payload.get("address_line1")),
			"address_line2": _as_str(payload.get("address_line2")),
			"city": _as_str(payload.get("city")),
			"state": _as_str(payload.get("state")),
			"pincode": _as_str(payload.get("pincode")),
			"country": _as_str(payload.get("country")) or "Australia",
		}
	)
	return {
		"firelink_property_id": firelink_property_id,
		"firelink_ft_property_id": ft_property_id or None,
		"firelink_address_id": address_id,
		"created": created,
	}


def _upsert_ft_property_local(payload: dict[str, Any]) -> str:
	if not frappe.db.exists("DocType", "FT Property"):
		return ""
	firelink_property_id = _as_str(payload.get("firelink_property_id"))
	address_id = _as_str(payload.get("firelink_address_id"))
	display_name = _as_str(payload.get("property_display_name")) or address_id or firelink_property_id

	existing_name = ""
	if firelink_property_id and frappe.db.has_column("FT Property", "firelink_uid"):
		existing_name = _as_str(
			frappe.db.get_value("FT Property", {"firelink_uid": firelink_property_id}, "name")
		)
	doc = frappe.get_doc("FT Property", existing_name) if existing_name else frappe.new_doc("FT Property")
	meta = frappe.get_meta("FT Property")

	def set_if(fieldname: str, value: Any):
		if fieldname in meta.fields_map and value is not None and str(value) != "":
			setattr(doc, fieldname, value)

	set_if("property_name", display_name)
	set_if("property_address", address_id)
	set_if("firelink_uid", firelink_property_id)
	if payload.get("property_lat") is not None:
		set_if("property_lat", _as_float(payload.get("property_lat"), 0.0))
	if payload.get("property_lng") is not None:
		set_if("property_lng", _as_float(payload.get("property_lng"), 0.0))
	set_if("ft_property_address_line1", _as_str(payload.get("address_line1")))
	set_if("ft_property_address_line2", _as_str(payload.get("address_line2")))
	set_if("ft_property_suburb", _as_str(payload.get("city")))
	set_if("ft_property_state", _as_str(payload.get("state")))
	set_if("ft_property_postcode", _as_str(payload.get("pincode")))
	set_if("ft_property_country", _as_str(payload.get("country")) or "Australia")

	if existing_name:
		doc.save(ignore_permissions=True)
	else:
		doc.insert(ignore_permissions=True)
	return _as_str(doc.name)


def _upsert_fl_asset_local(payload: dict[str, Any]) -> dict[str, Any]:
	property_id = _as_str(payload.get("firelink_property_id"))
	if not property_id:
		frappe.throw("firelink_property_id is required", frappe.ValidationError)
	asset_id = _as_str(payload.get("firelink_asset_id")) or _as_str(payload.get("local_asset_id"))
	if not asset_id:
		frappe.throw("local_asset_id is required", frappe.ValidationError)
	values = {
		"asset_property": property_id,
		"asset_type_code": _as_str(payload.get("asset_type_code")),
		"asset_label": _as_str(payload.get("asset_label")),
		"asset_serial": _as_str(payload.get("asset_serial")),
		"asset_identifier": _as_str(payload.get("asset_identifier")),
		"asset_status": _as_str(payload.get("asset_status")),
	}
	if frappe.db.exists("FL Asset", asset_id):
		doc = frappe.get_doc("FL Asset", asset_id)
		for fieldname, value in values.items():
			setattr(doc, fieldname, value)
		doc.save(ignore_permissions=True)
		created = False
	else:
		doc = frappe.get_doc({"doctype": "FL Asset", "name": asset_id, **values})
		doc.insert(ignore_permissions=True)
		created = True
	return {"firelink_asset_id": doc.name, "created": created}


def _upsert_fl_defect_local(payload: dict[str, Any]) -> dict[str, Any]:
	property_id = _as_str(payload.get("firelink_property_id"))
	if not property_id:
		frappe.throw("firelink_property_id is required", frappe.ValidationError)
	defect_id = _as_str(payload.get("firelink_defect_id")) or _as_str(payload.get("local_defect_id"))
	if not defect_id:
		frappe.throw("local_defect_id is required", frappe.ValidationError)
	values = {
		"defect_property": property_id,
		"defect_asset": _as_str(payload.get("firelink_asset_id")),
		"defect_template_code": _as_str(payload.get("defect_template_code")),
		"defect_severity": _as_str(payload.get("defect_severity")),
		"defect_status": _as_str(payload.get("defect_status")),
		"defect_summary": _as_str(payload.get("defect_summary"))[:140],
	}
	if frappe.db.exists("FL Defect", defect_id):
		doc = frappe.get_doc("FL Defect", defect_id)
		for fieldname, value in values.items():
			setattr(doc, fieldname, value)
		doc.save(ignore_permissions=True)
		created = False
	else:
		doc = frappe.get_doc({"doctype": "FL Defect", "name": defect_id, **values})
		doc.insert(ignore_permissions=True)
		created = True
	return {"firelink_defect_id": doc.name, "created": created}


def _upsert_remote_fl_doctype(doctype: str, name: str, values: dict[str, Any]) -> dict[str, Any]:
	if not name:
		frappe.throw(f"{doctype} name is required", frappe.ValidationError)
	filtered = {k: v for k, v in (values or {}).items() if v is not None}
	filtered["name"] = name
	exists = False
	try:
		existing = _firelink_http(
			"GET",
			f"/api/resource/{quote(doctype, safe='')}/{quote(name, safe='')}",
			params={"fields": json.dumps(["name"])},
		)
		exists = isinstance(existing.get("data"), dict)
	except Exception:
		exists = False
	if exists:
		_firelink_http(
			"PUT",
			f"/api/resource/{quote(doctype, safe='')}/{quote(name, safe='')}",
			data={"data": json.dumps(filtered)},
			headers={"Content-Type": "application/x-www-form-urlencoded"},
		)
		return {"name": name, "created": False}
	create_doc = {"doctype": doctype, **filtered}
	res = _firelink_http(
		"POST",
		"/api/method/frappe.client.insert",
		data={"doc": json.dumps(create_doc)},
		headers={"Content-Type": "application/x-www-form-urlencoded"},
	)
	created_name = _as_str(
		(res.get("message") or {}).get("name") if isinstance(res.get("message"), dict) else ""
	)
	return {"name": created_name or name, "created": True}


@frappe.whitelist(methods=["POST"])
def firelink_property_sync(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	address_payload = {
		"address_title": _as_str(kwargs.get("address_title")) or None,
		"address_line1": _as_str(kwargs.get("address_line1")),
		"address_line2": _as_str(kwargs.get("address_line2")) or None,
		"city": _as_str(kwargs.get("city")) or None,
		"state": _as_str(kwargs.get("state")) or None,
		"pincode": _as_str(kwargs.get("pincode")) or None,
		"country": _as_str(kwargs.get("country")) or "Australia",
		"place_id": _as_str(kwargs.get("place_id")) or None,
	}
	address_result = firelink_address_resolve_or_create(**address_payload)
	firelink_address_id = _as_str((address_result or {}).get("firelink_address_id"))
	if not firelink_address_id:
		frappe.throw("Unable to resolve FireLink address", frappe.ValidationError)

	payload = {
		"firelink_address_id": firelink_address_id,
		"firelink_property_id": _as_str(kwargs.get("firelink_property_id")) or None,
		"property_display_name": _as_str(kwargs.get("property_display_name")) or None,
		"property_lat": kwargs.get("property_lat"),
		"property_lng": kwargs.get("property_lng"),
		"address_title": _as_str(kwargs.get("address_title")) or None,
		"address_line1": _as_str(kwargs.get("address_line1")) or None,
		"address_line2": _as_str(kwargs.get("address_line2")) or None,
		"city": _as_str(kwargs.get("city")) or None,
		"state": _as_str(kwargs.get("state")) or None,
		"pincode": _as_str(kwargs.get("pincode")) or None,
		"country": _as_str(kwargs.get("country")) or "Australia",
	}
	if _is_firelink_local_site():
		out = _upsert_fl_property_local(payload)
	else:
		try:
			out = _firelink_remote_bridge_call(
				"/api/method/firtrackpro.api.integrations.firelink_property_sync_bridge",
				_remote_bridge_payload(payload),
			)
		except Exception:
			remote = _upsert_remote_fl_doctype(
				"FL Property",
				_as_str(payload.get("firelink_property_id")) or firelink_address_id,
				{
					"property_display_name": _as_str(payload.get("property_display_name"))
					or _as_str(payload.get("address_title"))
					or firelink_address_id,
					"property_address_json": json.dumps(
						{
							"address_id": firelink_address_id,
							"address_title": _as_str(payload.get("address_title")),
							"address_line1": _as_str(payload.get("address_line1")),
							"address_line2": _as_str(payload.get("address_line2")),
							"city": _as_str(payload.get("city")),
							"state": _as_str(payload.get("state")),
							"pincode": _as_str(payload.get("pincode")),
							"country": _as_str(payload.get("country")) or "Australia",
						},
						separators=(",", ":"),
					),
					"property_lat": _as_float(payload.get("property_lat"), 0.0),
					"property_lng": _as_float(payload.get("property_lng"), 0.0),
				},
			)
			out = {
				"firelink_property_id": _as_str(remote.get("name")),
				"created": bool(remote.get("created")),
			}
	return {"firelink_address_id": firelink_address_id, **(out or {})}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def firelink_property_sync_bridge(**kwargs):
	if not _is_valid_bridge_call():
		frappe.throw("Bridge token or approved firetrackpro origin is required", frappe.PermissionError)
	return _upsert_fl_property_local(kwargs)


@frappe.whitelist(methods=["POST"])
def firelink_asset_sync(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	status = _as_str(kwargs.get("asset_status")).lower()
	if status not in {"active", "inactive", "retired"}:
		status = "active"
	payload = {
		"firelink_property_id": _as_str(kwargs.get("firelink_property_id")),
		"firelink_asset_id": _as_str(kwargs.get("firelink_asset_id")) or None,
		"local_asset_id": _as_str(kwargs.get("local_asset_id")),
		"asset_type_code": _as_str(kwargs.get("asset_type_code")) or None,
		"asset_label": _as_str(kwargs.get("asset_label")) or None,
		"asset_serial": _as_str(kwargs.get("asset_serial")) or None,
		"asset_identifier": _as_str(kwargs.get("asset_identifier")) or None,
		"asset_status": status,
	}
	if _is_firelink_local_site():
		return _upsert_fl_asset_local(payload)
	try:
		return _firelink_remote_bridge_call(
			"/api/method/firtrackpro.api.integrations.firelink_asset_sync_bridge",
			_remote_bridge_payload(payload),
		)
	except Exception:
		remote = _upsert_remote_fl_doctype(
			"FL Asset",
			_as_str(payload.get("firelink_asset_id")) or _as_str(payload.get("local_asset_id")),
			{
				"asset_property": _as_str(payload.get("firelink_property_id")),
				"asset_type_code": _as_str(payload.get("asset_type_code")),
				"asset_label": _as_str(payload.get("asset_label")),
				"asset_serial": _as_str(payload.get("asset_serial")),
				"asset_identifier": _as_str(payload.get("asset_identifier")),
				"asset_status": _as_str(payload.get("asset_status")),
			},
		)
		return {"firelink_asset_id": _as_str(remote.get("name")), "created": bool(remote.get("created"))}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def firelink_asset_sync_bridge(**kwargs):
	if not _is_valid_bridge_call():
		frappe.throw("Bridge token or approved firetrackpro origin is required", frappe.PermissionError)
	return _upsert_fl_asset_local(kwargs)


@frappe.whitelist(methods=["POST"])
def firelink_defect_sync(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	payload = {
		"firelink_property_id": _as_str(kwargs.get("firelink_property_id")),
		"firelink_defect_id": _as_str(kwargs.get("firelink_defect_id")) or None,
		"local_defect_id": _as_str(kwargs.get("local_defect_id")),
		"firelink_asset_id": _as_str(kwargs.get("firelink_asset_id")) or None,
		"defect_template_code": _as_str(kwargs.get("defect_template_code")) or None,
		"defect_severity": _as_str(kwargs.get("defect_severity")) or None,
		"defect_status": _as_str(kwargs.get("defect_status")) or None,
		"defect_summary": _as_str(kwargs.get("defect_summary"))[:140] or None,
	}
	if _is_firelink_local_site():
		return _upsert_fl_defect_local(payload)
	try:
		return _firelink_remote_bridge_call(
			"/api/method/firtrackpro.api.integrations.firelink_defect_sync_bridge",
			_remote_bridge_payload(payload),
		)
	except Exception:
		remote = _upsert_remote_fl_doctype(
			"FL Defect",
			_as_str(payload.get("firelink_defect_id")) or _as_str(payload.get("local_defect_id")),
			{
				"defect_property": _as_str(payload.get("firelink_property_id")),
				"defect_asset": _as_str(payload.get("firelink_asset_id")),
				"defect_template_code": _as_str(payload.get("defect_template_code")),
				"defect_severity": _as_str(payload.get("defect_severity")),
				"defect_status": _as_str(payload.get("defect_status")),
				"defect_summary": _as_str(payload.get("defect_summary"))[:140],
			},
		)
		return {"firelink_defect_id": _as_str(remote.get("name")), "created": bool(remote.get("created"))}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def firelink_defect_sync_bridge(**kwargs):
	if not _is_valid_bridge_call():
		frappe.throw("Bridge token or approved firetrackpro origin is required", frappe.PermissionError)
	return _upsert_fl_defect_local(kwargs)
