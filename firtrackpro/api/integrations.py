import json
from typing import Any
from urllib.parse import quote, urlparse

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


def _norm(value: Any) -> str:
	return _as_str(value).lower().strip()


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
	row_line1 = _norm(existing.get("address_line1"))
	in_line1 = _norm(incoming.get("address_line1"))
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
		"notes",
		"modified",
	]


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
	doc = frappe.get_doc(
		{
			"doctype": "FL Site Subscription",
			"site_host": _normalize_site_host(kwargs.get("site_host")),
			"site_alias": _as_str(kwargs.get("site_alias")) or None,
			"customer": _as_str(kwargs.get("customer")),
			"subscription_plan": _as_str(kwargs.get("subscription_plan")) or None,
			"subscription_status": _as_str(kwargs.get("subscription_status")) or "Active",
			"base_users_included": int(float(kwargs.get("base_users_included") or 0)),
			"extra_users_purchased": int(float(kwargs.get("extra_users_purchased") or 0)),
			"allowed_users_total": int(float(kwargs.get("allowed_users_total") or 0)),
			"billing_cycle": _as_str(kwargs.get("billing_cycle")) or "Monthly",
			"next_invoice_date": _as_str(kwargs.get("next_invoice_date")) or None,
			"subscription_reference": _as_str(kwargs.get("subscription_reference")) or None,
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
		"notes",
	):
		if key in kwargs and kwargs.get(key) is not None:
			val = _as_str(kwargs.get(key))
			doc.set(key, _normalize_site_host(val) if key == "site_host" else (val or None))
	for key in ("base_users_included", "extra_users_purchased", "allowed_users_total"):
		if key in kwargs and kwargs.get(key) is not None and str(kwargs.get(key)).strip() != "":
			doc.set(key, int(float(kwargs.get(key) or 0)))
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
