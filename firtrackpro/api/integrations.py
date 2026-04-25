import json
from typing import Any

import frappe

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
	frappe.throw(
		"Google Places API key is not configured on the server. "
		"Set google_maps_api_key in site_config.json.",
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
	address_title = _as_str(result.get("name")) or line1 or formatted_address.split(",")[0].strip() or "Site Address"
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
