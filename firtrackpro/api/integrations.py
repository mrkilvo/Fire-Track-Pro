import base64
import hashlib
import hmac
import json
import os
import re
import shlex
import subprocess
from datetime import datetime, timezone, timedelta
from typing import Any
from urllib.parse import quote, urlencode, urlparse

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
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

FIRELINK_HAPROXY_PROVISION_COMMAND_CANDIDATES = (
	"firelink_haproxy_provision_command",
	"firtrackpro_firelink_haproxy_provision_command",
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
		"scopes": "openid profile email offline_access",
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


def _normalize_provider_name(value: Any, default: str = "Xero") -> str:
	raw = _as_str(value)
	if raw in PROVIDERS:
		return raw
	lower = raw.lower().replace(" ", "").replace("_", "")
	if lower == "myob":
		return "MYOB"
	if lower == "xero":
		return "Xero"
	if lower == "quickbooks":
		return "QuickBooks"
	if lower == "custom":
		return "Custom"
	return default


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
			"xeroAccessToken": _as_str(row.get("xeroAccessToken")),
			"xeroRefreshToken": _as_str(row.get("xeroRefreshToken")),
			"xeroTokenExpiresAt": _as_str(row.get("xeroTokenExpiresAt")),
			"xeroConnectedAt": _as_str(row.get("xeroConnectedAt")),
			"xeroState": _as_str(row.get("xeroState")),
			"xeroConnectionsJson": _as_str(row.get("xeroConnectionsJson")),
			"quickbooksAccessToken": _as_str(row.get("quickbooksAccessToken")),
			"quickbooksRefreshToken": _as_str(row.get("quickbooksRefreshToken")),
			"quickbooksTokenExpiresAt": _as_str(row.get("quickbooksTokenExpiresAt")),
			"quickbooksConnectedAt": _as_str(row.get("quickbooksConnectedAt")),
			"quickbooksState": _as_str(row.get("quickbooksState")),
			"quickbooksRealmId": _as_str(row.get("quickbooksRealmId")),
			"syncCustomers": _as_bool(row.get("syncCustomers")),
			"syncInvoices": _as_bool(row.get("syncInvoices")),
			"syncPayments": _as_bool(row.get("syncPayments")),
			"syncSuppliers": _as_bool(row.get("syncSuppliers")),
		}
	return out


def _save_records(records: dict[str, Any]) -> None:
	frappe.db.set_default(DEFAULTS_KEY, json.dumps(records))


def _utc_iso_now() -> str:
	return datetime.now(timezone.utc).isoformat()


def _integration_record(provider: str) -> dict[str, Any]:
	records = _load_records()
	if provider not in records:
		frappe.throw(f"Unknown provider: {provider}", frappe.ValidationError)
	return records[provider]


def _persist_integration_record(provider: str, row: dict[str, Any]) -> dict[str, Any]:
	records = _load_records()
	records[provider] = row
	_save_records(records)
	return records[provider]


def _xero_redirect_uri(row: dict[str, Any] | None = None) -> str:
	# Prefer explicit callback config to avoid host/proxy ambiguity (localhost/dev/prod).
	row = row or {}
	candidates = [
		_as_str(row.get("xeroRedirectUri")),
		_as_str(row.get("redirectUri")),
		_as_str(frappe.conf.get("xero_oauth_redirect_uri")),
		_as_str(frappe.conf.get("firtrackpro_xero_oauth_redirect_uri")),
	]
	for candidate in candidates:
		if candidate:
			return candidate.rstrip("/")

	def _force_https_if_firetrack(url: str) -> str:
		value = _as_str(url).strip()
		if not value:
			return value
		lower = value.lower()
		if ".firetrackpro.com.au" in lower and lower.startswith("http://"):
			return "https://" + value[7:]
		return value

	host_name = _force_https_if_firetrack(_as_str(frappe.conf.get("host_name")).rstrip("/"))
	if host_name:
		return f"{host_name}/api/method/firtrackpro.api.integrations.xero_oauth_callback"

	base = _force_https_if_firetrack(_as_str(frappe.utils.get_url()).rstrip("/"))
	return f"{base}/api/method/firtrackpro.api.integrations.xero_oauth_callback"


def _xero_basic_auth(client_id: str, client_secret: str) -> str:
	raw = f"{client_id}:{client_secret}".encode("utf-8")
	return base64.b64encode(raw).decode("utf-8")


def _xero_refresh_if_needed(config: dict[str, Any]) -> dict[str, Any]:
	access_token = _as_str(config.get("xeroAccessToken"))
	refresh_token = _as_str(config.get("xeroRefreshToken"))
	expires_at = _as_str(config.get("xeroTokenExpiresAt"))
	if not access_token:
		frappe.throw("Xero is not connected. Run Connect Xero first.", frappe.ValidationError)
	if not refresh_token:
		return config
	if expires_at:
		try:
			exp_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
			if exp_dt > datetime.now(timezone.utc):
				return config
		except Exception:
			pass

	if requests is None:
		frappe.throw("Xero token refresh is unavailable (requests library missing).")

	client_id = _as_str(config.get("clientId"))
	client_secret = _as_str(config.get("clientSecret"))
	token_url = _as_str(config.get("tokenUrl")) or _as_str(PROVIDER_DEFAULTS["Xero"].get("tokenUrl"))
	if not client_id or not client_secret or not token_url:
		frappe.throw("Xero Client ID/Secret and Token URL are required for refresh.", frappe.ValidationError)

	headers = {
		"Authorization": f"Basic {_xero_basic_auth(client_id, client_secret)}",
		"Content-Type": "application/x-www-form-urlencoded",
		"Accept": "application/json",
	}
	form = {"grant_type": "refresh_token", "refresh_token": refresh_token}
	resp = requests.post(token_url, headers=headers, data=form, timeout=20)
	if not resp.ok:
		detail = _as_str(resp.text)
		detail_l = detail.lower()
		if resp.status_code == 400 and ("invalid_grant" in detail_l or "refresh token not found" in detail_l):
			# Xero no longer accepts the refresh token (revoked/rotated/expired).
			# Clear local oauth tokens so the portal can force a clean reconnect flow.
			config["xeroAccessToken"] = ""
			config["xeroRefreshToken"] = ""
			config["xeroTokenExpiresAt"] = ""
			config["xeroConnectionsJson"] = "[]"
			frappe.throw(
				"Xero refresh token is invalid or missing in Xero. Reconnect Xero in Integrations to continue sync.",
				frappe.ValidationError,
			)
		frappe.throw(f"Xero refresh failed ({resp.status_code}): {detail}", frappe.ValidationError)
	data = resp.json() if hasattr(resp, "json") else {}
	config["xeroAccessToken"] = _as_str(data.get("access_token")) or access_token
	config["xeroRefreshToken"] = _as_str(data.get("refresh_token")) or refresh_token
	expires_in = _as_int(data.get("expires_in"), 1800)
	config["xeroTokenExpiresAt"] = (datetime.now(timezone.utc).timestamp() + expires_in)
	config["xeroTokenExpiresAt"] = datetime.fromtimestamp(float(config["xeroTokenExpiresAt"]), tz=timezone.utc).isoformat()
	config["xeroConnectedAt"] = _utc_iso_now()
	return config


def _xero_is_auth_unsuccessful(resp: Any) -> bool:
	if resp is None:
		return False
	status = int(getattr(resp, "status_code", 0) or 0)
	detail = _as_str(getattr(resp, "text", "")).lower()
	if status == 401:
		return True
	if status == 403 and "authenticationunsuccessful" in detail:
		return True
	return False


def _xero_refresh_and_reselect_tenant(config: dict[str, Any]) -> dict[str, Any]:
	config = _xero_refresh_if_needed(config)
	connections: list[dict[str, Any]] = []
	try:
		connections = _xero_fetch_connections(config)
	except Exception:
		connections = []
	current = _as_str(config.get("tenantId"))
	tenant_ids = [
		_as_str((row or {}).get("tenantId") or (row or {}).get("tenant_id"))
		for row in (connections or [])
		if isinstance(row, dict)
	]
	tenant_ids = [x for x in tenant_ids if x]
	if tenant_ids and current not in tenant_ids:
		config["tenantId"] = tenant_ids[0]
	if not _as_str(config.get("tenantId")) and tenant_ids:
		config["tenantId"] = tenant_ids[0]
	if connections:
		config["xeroConnectionsJson"] = json.dumps(connections)
	return config


def _xero_fetch_connections(config: dict[str, Any]) -> list[dict[str, Any]]:
	if requests is None:
		frappe.throw("Xero calls are unavailable (requests library missing).")
	access_token = _as_str(config.get("xeroAccessToken"))
	if not access_token:
		frappe.throw("Xero is not connected. Run Connect Xero first.", frappe.ValidationError)
	resp = requests.get(
		"https://api.xero.com/connections",
		headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
		timeout=20,
	)
	if resp.status_code == 401:
		config = _xero_refresh_if_needed(config)
		access_token = _as_str(config.get("xeroAccessToken"))
		resp = requests.get(
			"https://api.xero.com/connections",
			headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
			timeout=20,
		)
	if not resp.ok:
		detail = _as_str(resp.text)
		frappe.throw(f"Xero connections failed ({resp.status_code}): {detail}", frappe.ValidationError)
	rows = resp.json() if hasattr(resp, "json") else []
	return rows if isinstance(rows, list) else []




def _xero_remote_disconnect(config: dict[str, Any]) -> dict[str, Any]:
	if requests is None:
		return {"ok": False, "message": "requests library missing"}
	access_token = _as_str(config.get("xeroAccessToken"))
	if not access_token:
		return {"ok": True, "message": "No Xero access token to revoke."}
	connections = []
	try:
		connections = _xero_fetch_connections(config)
	except Exception:
		connections = []
	failures: list[str] = []
	for row in (connections or []):
		if not isinstance(row, dict):
			continue
		conn_id = _as_str(row.get("id"))
		if not conn_id:
			continue
		resp = requests.delete(
			f"https://api.xero.com/connections/{conn_id}",
			headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
			timeout=20,
		)
		if resp.status_code == 401:
			config = _xero_refresh_if_needed(config)
			access_token = _as_str(config.get("xeroAccessToken"))
			resp = requests.delete(
				f"https://api.xero.com/connections/{conn_id}",
				headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
				timeout=20,
			)
		if not resp.ok:
			failures.append(f"{conn_id}:{resp.status_code}")
	if failures:
		return {"ok": False, "message": f"Some Xero connections could not be revoked: {', '.join(failures)}"}
	return {"ok": True, "message": "Xero organization connections revoked."}
def _xero_fetch_contacts(config: dict[str, Any]) -> list[dict[str, Any]]:
	if requests is None:
		frappe.throw("Xero calls are unavailable (requests library missing).")
	access_token = _as_str(config.get("xeroAccessToken"))
	tenant_id = _as_str(config.get("tenantId"))
	if not access_token:
		frappe.throw("Xero is not connected. Run Connect Xero first.", frappe.ValidationError)
	if not tenant_id:
		frappe.throw("Xero tenant is not linked yet. Click Check Xero Orgs first.", frappe.ValidationError)

	headers = {
		"Authorization": f"Bearer {access_token}",
		"Accept": "application/json",
		"xero-tenant-id": tenant_id,
	}
	resp = requests.get("https://api.xero.com/api.xro/2.0/Contacts", headers=headers, timeout=25)
	if _xero_is_auth_unsuccessful(resp):
		config = _xero_refresh_and_reselect_tenant(config)
		headers["Authorization"] = f"Bearer {_as_str(config.get('xeroAccessToken'))}"
		headers["xero-tenant-id"] = _as_str(config.get("tenantId"))
		resp = requests.get("https://api.xero.com/api.xro/2.0/Contacts", headers=headers, timeout=25)
	if not resp.ok:
		detail = _as_str(resp.text)
		if _xero_is_auth_unsuccessful(resp):
			frappe.throw("Xero authentication failed for the selected organization. Reconnect Xero and re-select the org in Integrations.", frappe.ValidationError)
		frappe.throw(f"Xero contacts fetch failed ({resp.status_code}): {detail}", frappe.ValidationError)
	payload = resp.json() if hasattr(resp, "json") else {}
	rows = payload.get("Contacts") if isinstance(payload, dict) else []
	return rows if isinstance(rows, list) else []


def _ensure_customer_xero_fields() -> None:
	fields = {
		"Customer": [
			{
				"fieldname": "xero_contact_id",
				"label": "Xero Contact ID",
				"fieldtype": "Data",
				"insert_after": "customer_name",
				"read_only": 1,
				"no_copy": 1,
				"unique": 1,
			},
			{
				"fieldname": "xero_contact_number",
				"label": "Xero Contact Number",
				"fieldtype": "Data",
				"insert_after": "xero_contact_id",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "xero_last_synced_at",
				"label": "Xero Last Synced At",
				"fieldtype": "Datetime",
				"insert_after": "xero_contact_number",
				"read_only": 1,
				"no_copy": 1,
			},
		]
	}
	create_custom_fields(fields, update=True)


def _ensure_supplier_xero_fields() -> None:
	fields = {
		"Supplier": [
			{
				"fieldname": "xero_contact_id",
				"label": "Xero Contact ID",
				"fieldtype": "Data",
				"insert_after": "supplier_name",
				"read_only": 1,
				"no_copy": 1,
				"unique": 1,
			},
			{
				"fieldname": "xero_contact_number",
				"label": "Xero Contact Number",
				"fieldtype": "Data",
				"insert_after": "xero_contact_id",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "xero_last_synced_at",
				"label": "Xero Last Synced At",
				"fieldtype": "Datetime",
				"insert_after": "xero_contact_number",
				"read_only": 1,
				"no_copy": 1,
			},
		]
	}
	create_custom_fields(fields, update=True)


def _ensure_sales_invoice_xero_fields() -> None:
	fields = {
		"Sales Invoice": [
			{
				"fieldname": "xero_invoice_id",
				"label": "Xero Invoice ID",
				"fieldtype": "Data",
				"insert_after": "customer",
				"read_only": 1,
				"no_copy": 1,
				"unique": 1,
			},
			{
				"fieldname": "xero_invoice_number",
				"label": "Xero Invoice Number",
				"fieldtype": "Data",
				"insert_after": "xero_invoice_id",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "xero_last_synced_at",
				"label": "Xero Last Synced At",
				"fieldtype": "Datetime",
				"insert_after": "xero_invoice_number",
				"read_only": 1,
				"no_copy": 1,
			},
		]
	}
	create_custom_fields(fields, update=True)


def _ensure_payment_entry_xero_fields() -> None:
	fields = {
		"Payment Entry": [
			{
				"fieldname": "xero_payment_id",
				"label": "Xero Payment ID",
				"fieldtype": "Data",
				"insert_after": "reference_no",
				"read_only": 1,
				"no_copy": 1,
				"unique": 1,
			},
			{
				"fieldname": "xero_payment_ref",
				"label": "Xero Payment Reference",
				"fieldtype": "Data",
				"insert_after": "xero_payment_id",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "xero_last_synced_at",
				"label": "Xero Last Synced At",
				"fieldtype": "Datetime",
				"insert_after": "xero_payment_ref",
				"read_only": 1,
				"no_copy": 1,
			},
		]
	}
	create_custom_fields(fields, update=True)


def _ensure_item_xero_fields() -> None:
	fields = {
		"Item": [
			{
				"fieldname": "xero_item_id",
				"label": "Xero Item ID",
				"fieldtype": "Data",
				"insert_after": "item_name",
				"read_only": 1,
				"no_copy": 1,
				"unique": 1,
			},
			{
				"fieldname": "xero_item_code",
				"label": "Xero Item Code",
				"fieldtype": "Data",
				"insert_after": "xero_item_id",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "xero_last_synced_at",
				"label": "Xero Last Synced At",
				"fieldtype": "Datetime",
				"insert_after": "xero_item_code",
				"read_only": 1,
				"no_copy": 1,
			},
		]
	}
	create_custom_fields(fields, update=True)


def _ensure_accounting_sync_meta_fields() -> None:
	fields = {
		"Customer": [
			{
				"fieldname": "accounting_sync_status",
				"label": "Accounting Sync Status",
				"fieldtype": "Select",
				"options": "\nNot Synced\nSynced\nError",
				"insert_after": "xero_last_synced_at",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "accounting_last_synced_at",
				"label": "Accounting Last Synced At",
				"fieldtype": "Datetime",
				"insert_after": "accounting_sync_status",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "accounting_provider",
				"label": "Accounting Provider",
				"fieldtype": "Data",
				"insert_after": "accounting_last_synced_at",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "accounting_external_id",
				"label": "Accounting External ID",
				"fieldtype": "Data",
				"insert_after": "accounting_provider",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "accounting_sync_error",
				"label": "Accounting Sync Error",
				"fieldtype": "Small Text",
				"insert_after": "accounting_external_id",
				"read_only": 1,
				"no_copy": 1,
			},
		],
		"Supplier": [
			{
				"fieldname": "accounting_sync_status",
				"label": "Accounting Sync Status",
				"fieldtype": "Select",
				"options": "\nNot Synced\nSynced\nError",
				"insert_after": "xero_last_synced_at",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "accounting_last_synced_at",
				"label": "Accounting Last Synced At",
				"fieldtype": "Datetime",
				"insert_after": "accounting_sync_status",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "accounting_provider",
				"label": "Accounting Provider",
				"fieldtype": "Data",
				"insert_after": "accounting_last_synced_at",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "accounting_external_id",
				"label": "Accounting External ID",
				"fieldtype": "Data",
				"insert_after": "accounting_provider",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "accounting_sync_error",
				"label": "Accounting Sync Error",
				"fieldtype": "Small Text",
				"insert_after": "accounting_external_id",
				"read_only": 1,
				"no_copy": 1,
			},
		],
		"Sales Invoice": [
			{
				"fieldname": "accounting_sync_status",
				"label": "Accounting Sync Status",
				"fieldtype": "Select",
				"options": "\nNot Synced\nSynced\nError",
				"insert_after": "xero_last_synced_at",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "accounting_last_synced_at",
				"label": "Accounting Last Synced At",
				"fieldtype": "Datetime",
				"insert_after": "accounting_sync_status",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "accounting_provider",
				"label": "Accounting Provider",
				"fieldtype": "Data",
				"insert_after": "accounting_last_synced_at",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "accounting_external_id",
				"label": "Accounting External ID",
				"fieldtype": "Data",
				"insert_after": "accounting_provider",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "accounting_sync_error",
				"label": "Accounting Sync Error",
				"fieldtype": "Small Text",
				"insert_after": "accounting_external_id",
				"read_only": 1,
				"no_copy": 1,
			},
		],
		"Payment Entry": [
			{
				"fieldname": "accounting_sync_status",
				"label": "Accounting Sync Status",
				"fieldtype": "Select",
				"options": "\nNot Synced\nSynced\nError",
				"insert_after": "reference_no",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "accounting_last_synced_at",
				"label": "Accounting Last Synced At",
				"fieldtype": "Datetime",
				"insert_after": "accounting_sync_status",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "accounting_provider",
				"label": "Accounting Provider",
				"fieldtype": "Data",
				"insert_after": "accounting_last_synced_at",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "accounting_external_id",
				"label": "Accounting External ID",
				"fieldtype": "Data",
				"insert_after": "accounting_provider",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "accounting_sync_error",
				"label": "Accounting Sync Error",
				"fieldtype": "Small Text",
				"insert_after": "accounting_external_id",
				"read_only": 1,
				"no_copy": 1,
			},
		],
	}
	create_custom_fields(fields, update=True)


def _set_accounting_sync_meta(
	doctype: str,
	docname: str,
	provider: str,
	status: str,
	external_id: str = "",
	error_message: str = "",
) -> None:
	if not docname or not frappe.db.exists(doctype, docname):
		return
	frappe.db.set_value(
		doctype,
		docname,
		{
			"accounting_sync_status": status,
			"accounting_last_synced_at": frappe.utils.now_datetime(),
			"accounting_provider": provider,
			"accounting_external_id": external_id or "",
			"accounting_sync_error": error_message or "",
		},
		update_modified=False,
	)


@frappe.whitelist(methods=["POST"])
def ensure_xero_sync_fields(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	_ensure_customer_xero_fields()
	_ensure_supplier_xero_fields()
	_ensure_sales_invoice_xero_fields()
	_ensure_payment_entry_xero_fields()
	_ensure_item_xero_fields()
	_ensure_accounting_sync_meta_fields()
	return {"ok": True, "message": "Xero customer sync fields are ready."}


def _first_contact_value(contact: dict[str, Any], field_name: str) -> str:
	rows = contact.get("Phones")
	if isinstance(rows, list):
		for row in rows:
			if not isinstance(row, dict):
				continue
			if field_name == "PhoneNumber":
				val = _as_str(row.get("PhoneNumber"))
				if val:
					return val
	return ""


def _primary_email(contact: dict[str, Any]) -> str:
	rows = contact.get("EmailAddress")
	return _as_str(rows)


def _xero_contact_matches_entity(contact: dict[str, Any], entity: str) -> bool:
	entity_key = _as_str(entity).strip().lower()
	if not isinstance(contact, dict):
		return False
	if entity_key not in {"customer", "supplier"}:
		return True
	has_customer = "IsCustomer" in contact
	has_supplier = "IsSupplier" in contact
	is_customer = _as_bool(contact.get("IsCustomer")) if has_customer else False
	is_supplier = _as_bool(contact.get("IsSupplier")) if has_supplier else False
	if entity_key == "customer":
		if has_customer:
			return is_customer
		if has_supplier and is_supplier:
			return False
		return True
	if has_supplier:
		return is_supplier
	if has_customer and is_customer:
		return False
	return True


def _upsert_customer_from_xero_contact(contact: dict[str, Any]) -> str:
	contact_id = _as_str(contact.get("ContactID"))
	contact_name = _as_str(contact.get("Name"))
	contact_number = _as_str(contact.get("ContactNumber"))
	email = _primary_email(contact)
	phone = _first_contact_value(contact, "PhoneNumber")
	if not contact_id or not contact_name:
		return ""

	customer_name = ""
	if frappe.db.exists("Customer", {"xero_contact_id": contact_id}):
		customer_name = frappe.db.get_value("Customer", {"xero_contact_id": contact_id}, "name")
	elif email and frappe.db.exists("Customer", {"email_id": email}):
		customer_name = frappe.db.get_value("Customer", {"email_id": email}, "name")
	elif frappe.db.exists("Customer", {"customer_name": contact_name}):
		customer_name = frappe.db.get_value("Customer", {"customer_name": contact_name}, "name")

	if customer_name:
		doc = frappe.get_doc("Customer", customer_name)
	else:
		doc = frappe.new_doc("Customer")
		doc.customer_name = contact_name
		doc.customer_type = "Company"

	doc.customer_name = contact_name
	if email:
		doc.email_id = email
	if phone:
		doc.mobile_no = phone
	doc.xero_contact_id = contact_id
	doc.xero_contact_number = contact_number
	doc.xero_last_synced_at = frappe.utils.now_datetime()
	doc.accounting_sync_status = "Synced"
	doc.accounting_last_synced_at = frappe.utils.now_datetime()
	doc.accounting_provider = "Xero"
	doc.accounting_external_id = contact_id
	doc.accounting_sync_error = ""

	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)
	return _as_str(doc.name)


def _upsert_supplier_from_xero_contact(contact: dict[str, Any]) -> str:
	contact_id = _as_str(contact.get("ContactID"))
	contact_name = _as_str(contact.get("Name"))
	contact_number = _as_str(contact.get("ContactNumber"))
	email = _primary_email(contact)
	phone = _first_contact_value(contact, "PhoneNumber")
	if not contact_id or not contact_name:
		return ""

	supplier_name = ""
	if frappe.db.exists("Supplier", {"xero_contact_id": contact_id}):
		supplier_name = frappe.db.get_value("Supplier", {"xero_contact_id": contact_id}, "name")
	elif email and frappe.db.exists("Supplier", {"email_id": email}):
		supplier_name = frappe.db.get_value("Supplier", {"email_id": email}, "name")
	elif frappe.db.exists("Supplier", {"supplier_name": contact_name}):
		supplier_name = frappe.db.get_value("Supplier", {"supplier_name": contact_name}, "name")

	if supplier_name:
		doc = frappe.get_doc("Supplier", supplier_name)
	else:
		doc = frappe.new_doc("Supplier")
		doc.supplier_name = contact_name
		doc.supplier_group = frappe.db.get_single_value("Buying Settings", "supplier_group") or "All Supplier Groups"
		doc.supplier_type = "Company"

	doc.supplier_name = contact_name
	if email:
		doc.email_id = email
	if phone:
		doc.mobile_no = phone
	doc.xero_contact_id = contact_id
	doc.xero_contact_number = contact_number
	doc.xero_last_synced_at = frappe.utils.now_datetime()
	doc.accounting_sync_status = "Synced"
	doc.accounting_last_synced_at = frappe.utils.now_datetime()
	doc.accounting_provider = "Xero"
	doc.accounting_external_id = contact_id
	doc.accounting_sync_error = ""
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)
	return _as_str(doc.name)


def _xero_fetch_invoices(config: dict[str, Any]) -> list[dict[str, Any]]:
	if requests is None:
		frappe.throw("Xero calls are unavailable (requests library missing).")
	access_token = _as_str(config.get("xeroAccessToken"))
	tenant_id = _as_str(config.get("tenantId"))
	if not access_token:
		frappe.throw("Xero is not connected. Run Connect Xero first.", frappe.ValidationError)
	if not tenant_id:
		frappe.throw("Xero tenant is not linked yet. Click Check Xero Orgs first.", frappe.ValidationError)

	headers = {
		"Authorization": f"Bearer {access_token}",
		"Accept": "application/json",
		"xero-tenant-id": tenant_id,
	}
	params = {"where": 'Type=="ACCREC"'}
	resp = requests.get("https://api.xero.com/api.xro/2.0/Invoices", headers=headers, params=params, timeout=30)
	if _xero_is_auth_unsuccessful(resp):
		config = _xero_refresh_and_reselect_tenant(config)
		headers["Authorization"] = f"Bearer {_as_str(config.get('xeroAccessToken'))}"
		headers["xero-tenant-id"] = _as_str(config.get("tenantId"))
		resp = requests.get("https://api.xero.com/api.xro/2.0/Invoices", headers=headers, params=params, timeout=30)
	if not resp.ok:
		detail = _as_str(resp.text)
		if _xero_is_auth_unsuccessful(resp):
			frappe.throw("Xero authentication failed for the selected organization. Reconnect Xero and re-select the org in Integrations.", frappe.ValidationError)
		frappe.throw(f"Xero invoices fetch failed ({resp.status_code}): {detail}", frappe.ValidationError)
	payload = resp.json() if hasattr(resp, "json") else {}
	rows = payload.get("Invoices") if isinstance(payload, dict) else []
	return rows if isinstance(rows, list) else []


def _xero_fetch_items(config: dict[str, Any]) -> list[dict[str, Any]]:
	if requests is None:
		frappe.throw("Xero calls are unavailable (requests library missing).")
	access_token = _as_str(config.get("xeroAccessToken"))
	tenant_id = _as_str(config.get("tenantId"))
	if not access_token:
		frappe.throw("Xero is not connected. Run Connect Xero first.", frappe.ValidationError)
	if not tenant_id:
		frappe.throw("Xero tenant is not linked yet. Click Check Xero Orgs first.", frappe.ValidationError)

	headers = {
		"Authorization": f"Bearer {access_token}",
		"Accept": "application/json",
		"xero-tenant-id": tenant_id,
	}
	resp = requests.get("https://api.xero.com/api.xro/2.0/Items", headers=headers, timeout=30)
	if _xero_is_auth_unsuccessful(resp):
		config = _xero_refresh_and_reselect_tenant(config)
		headers["Authorization"] = f"Bearer {_as_str(config.get('xeroAccessToken'))}"
		headers["xero-tenant-id"] = _as_str(config.get("tenantId"))
		resp = requests.get("https://api.xero.com/api.xro/2.0/Items", headers=headers, timeout=30)
	if not resp.ok:
		detail = _as_str(resp.text)
		if _xero_is_auth_unsuccessful(resp):
			frappe.throw("Xero authentication failed for the selected organization. Reconnect Xero and re-select the org in Integrations.", frappe.ValidationError)
		frappe.throw(f"Xero items fetch failed ({resp.status_code}): {detail}", frappe.ValidationError)
	payload = resp.json() if hasattr(resp, "json") else {}
	rows = payload.get("Items") if isinstance(payload, dict) else []
	return rows if isinstance(rows, list) else []


def _xero_fetch_payments(config: dict[str, Any]) -> list[dict[str, Any]]:
	if requests is None:
		frappe.throw("Xero calls are unavailable (requests library missing).")
	access_token = _as_str(config.get("xeroAccessToken"))
	tenant_id = _as_str(config.get("tenantId"))
	if not access_token:
		frappe.throw("Xero is not connected. Run Connect Xero first.", frappe.ValidationError)
	if not tenant_id:
		frappe.throw("Xero tenant is not linked yet. Click Check Xero Orgs first.", frappe.ValidationError)

	headers = {
		"Authorization": f"Bearer {access_token}",
		"Accept": "application/json",
		"xero-tenant-id": tenant_id,
	}
	resp = requests.get("https://api.xero.com/api.xro/2.0/Payments", headers=headers, timeout=30)
	if _xero_is_auth_unsuccessful(resp):
		config = _xero_refresh_and_reselect_tenant(config)
		headers["Authorization"] = f"Bearer {_as_str(config.get('xeroAccessToken'))}"
		headers["xero-tenant-id"] = _as_str(config.get("tenantId"))
		resp = requests.get("https://api.xero.com/api.xro/2.0/Payments", headers=headers, timeout=30)
	if not resp.ok:
		detail = _as_str(resp.text)
		if _xero_is_auth_unsuccessful(resp):
			frappe.throw("Xero authentication failed for the selected organization. Reconnect Xero and re-select the org in Integrations.", frappe.ValidationError)
		frappe.throw(f"Xero payments fetch failed ({resp.status_code}): {detail}", frappe.ValidationError)
	payload = resp.json() if hasattr(resp, "json") else {}
	rows = payload.get("Payments") if isinstance(payload, dict) else []
	return rows if isinstance(rows, list) else []


def _xero_fetch_credit_notes(config: dict[str, Any]) -> list[dict[str, Any]]:
	if requests is None:
		frappe.throw("Xero calls are unavailable (requests library missing).")
	headers = _xero_api_headers(config)
	resp = requests.get(
		"https://api.xero.com/api.xro/2.0/CreditNotes",
		headers=headers,
		params={"where": 'Type=="ACCRECCREDIT"'},
		timeout=30,
	)
	if _xero_is_auth_unsuccessful(resp):
		config = _xero_refresh_and_reselect_tenant(config)
		headers = _xero_api_headers(config)
		resp = requests.get(
			"https://api.xero.com/api.xro/2.0/CreditNotes",
			headers=headers,
			params={"where": 'Type=="ACCRECCREDIT"'},
			timeout=30,
		)
	if not resp.ok:
		detail = _as_str(resp.text)
		frappe.throw(f"Xero credit notes fetch failed ({resp.status_code}): {detail}", frappe.ValidationError)
	payload = resp.json() if hasattr(resp, "json") else {}
	rows = payload.get("CreditNotes") if isinstance(payload, dict) else []
	return rows if isinstance(rows, list) else []


def _xero_fetch_accounts(config: dict[str, Any]) -> list[dict[str, Any]]:
	if requests is None:
		frappe.throw("Xero calls are unavailable (requests library missing).")
	headers = _xero_api_headers(config)
	resp = requests.get("https://api.xero.com/api.xro/2.0/Accounts", headers=headers, timeout=30)
	if _xero_is_auth_unsuccessful(resp):
		config = _xero_refresh_and_reselect_tenant(config)
		headers = _xero_api_headers(config)
		resp = requests.get("https://api.xero.com/api.xro/2.0/Accounts", headers=headers, timeout=30)
	if not resp.ok:
		detail = _as_str(resp.text)
		frappe.throw(f"Xero accounts fetch failed ({resp.status_code}): {detail}", frappe.ValidationError)
	payload = resp.json() if hasattr(resp, "json") else {}
	rows = payload.get("Accounts") if isinstance(payload, dict) else []
	return rows if isinstance(rows, list) else []


def _xero_fetch_tax_rates(config: dict[str, Any]) -> list[dict[str, Any]]:
	if requests is None:
		frappe.throw("Xero calls are unavailable (requests library missing).")
	headers = _xero_api_headers(config)
	resp = requests.get("https://api.xero.com/api.xro/2.0/TaxRates", headers=headers, timeout=30)
	if _xero_is_auth_unsuccessful(resp):
		config = _xero_refresh_and_reselect_tenant(config)
		headers = _xero_api_headers(config)
		resp = requests.get("https://api.xero.com/api.xro/2.0/TaxRates", headers=headers, timeout=30)
	if not resp.ok:
		detail = _as_str(resp.text)
		frappe.throw(f"Xero tax rates fetch failed ({resp.status_code}): {detail}", frappe.ValidationError)
	payload = resp.json() if hasattr(resp, "json") else {}
	rows = payload.get("TaxRates") if isinstance(payload, dict) else []
	return rows if isinstance(rows, list) else []


def _xero_fetch_tracking_categories(config: dict[str, Any]) -> list[dict[str, Any]]:
	if requests is None:
		frappe.throw("Xero calls are unavailable (requests library missing).")
	headers = _xero_api_headers(config)
	resp = requests.get("https://api.xero.com/api.xro/2.0/TrackingCategories", headers=headers, timeout=30)
	if _xero_is_auth_unsuccessful(resp):
		config = _xero_refresh_and_reselect_tenant(config)
		headers = _xero_api_headers(config)
		resp = requests.get("https://api.xero.com/api.xro/2.0/TrackingCategories", headers=headers, timeout=30)
	if not resp.ok:
		detail = _as_str(resp.text)
		frappe.throw(f"Xero tracking categories fetch failed ({resp.status_code}): {detail}", frappe.ValidationError)
	payload = resp.json() if hasattr(resp, "json") else {}
	rows = payload.get("TrackingCategories") if isinstance(payload, dict) else []
	return rows if isinstance(rows, list) else []


def _xero_api_headers(config: dict[str, Any]) -> dict[str, str]:
	access_token = _as_str(config.get("xeroAccessToken"))
	tenant_id = _as_str(config.get("tenantId"))
	if not access_token:
		frappe.throw("Xero is not connected. Run Connect Xero first.", frappe.ValidationError)
	if not tenant_id:
		frappe.throw("Xero tenant is not linked yet. Click Check Xero Orgs first.", frappe.ValidationError)
	return {
		"Authorization": f"Bearer {access_token}",
		"Accept": "application/json",
		"Content-Type": "application/json",
		"xero-tenant-id": tenant_id,
	}


def _xero_api_json(
	config: dict[str, Any], method: str, path: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
	if requests is None:
		frappe.throw("Xero calls are unavailable (requests library missing).")
	headers = _xero_api_headers(config)
	url = f"https://api.xero.com/api.xro/2.0/{path.lstrip('/')}"
	resp = requests.request(method.upper(), url, headers=headers, json=payload or {}, timeout=30)
	if _xero_is_auth_unsuccessful(resp):
		config = _xero_refresh_and_reselect_tenant(config)
		headers = _xero_api_headers(config)
		resp = requests.request(method.upper(), url, headers=headers, json=payload or {}, timeout=30)
	if not resp.ok:
		detail = _as_str(resp.text)
		if _xero_is_auth_unsuccessful(resp):
			frappe.throw("Xero authentication failed for the selected organization. Reconnect Xero and re-select the org in Integrations.", frappe.ValidationError)
		frappe.throw(f"Xero API {method.upper()} {path} failed ({resp.status_code}): {detail}", frappe.ValidationError)
	data = resp.json() if hasattr(resp, "json") else {}
	return data if isinstance(data, dict) else {}


def _xero_push_contact(config: dict[str, Any], reference_name: str, doctype: str, document: dict[str, Any]) -> dict[str, Any]:
	name_val = _as_str(document.get("customer_name") or document.get("supplier_name") or document.get("name"))
	email_val = _as_str(document.get("email_id"))
	phone_val = _as_str(document.get("mobile_no"))
	if not name_val:
		if doctype == "Customer" and reference_name and frappe.db.exists("Customer", reference_name):
			name_val = _as_str(frappe.db.get_value("Customer", reference_name, "customer_name"))
			email_val = email_val or _as_str(frappe.db.get_value("Customer", reference_name, "email_id"))
			phone_val = phone_val or _as_str(frappe.db.get_value("Customer", reference_name, "mobile_no"))
		elif doctype == "Supplier" and reference_name and frappe.db.exists("Supplier", reference_name):
			name_val = _as_str(frappe.db.get_value("Supplier", reference_name, "supplier_name"))
			email_val = email_val or _as_str(frappe.db.get_value("Supplier", reference_name, "email_id"))
			phone_val = phone_val or _as_str(frappe.db.get_value("Supplier", reference_name, "mobile_no"))
	if not name_val:
		frappe.throw("Contact name is required for Xero sync.", frappe.ValidationError)

	contact_id = _as_str(document.get("xero_contact_id"))
	if not contact_id and reference_name and doctype and frappe.db.exists(doctype, reference_name):
		contact_id = _as_str(frappe.db.get_value(doctype, reference_name, "xero_contact_id"))

	contact_payload: dict[str, Any] = {"Name": name_val}
	if contact_id:
		contact_payload["ContactID"] = contact_id
	if email_val:
		contact_payload["EmailAddress"] = email_val
	if phone_val:
		contact_payload["Phones"] = [{"PhoneType": "MOBILE", "PhoneNumber": phone_val}]

	out = _xero_api_json(config, "PUT", "Contacts", {"Contacts": [contact_payload]})
	rows = out.get("Contacts") if isinstance(out.get("Contacts"), list) else []
	return rows[0] if rows and isinstance(rows[0], dict) else {}


def _xero_push_invoice(config: dict[str, Any], reference_name: str, document: dict[str, Any]) -> dict[str, Any]:
	invoice_doc = document or {}
	if reference_name and frappe.db.exists("Sales Invoice", reference_name):
		src = frappe.get_doc("Sales Invoice", reference_name)
		invoice_doc = {
			**invoice_doc,
			"customer": invoice_doc.get("customer") or _as_str(src.customer),
			"posting_date": invoice_doc.get("posting_date") or _as_str(src.posting_date),
			"due_date": invoice_doc.get("due_date") or _as_str(src.due_date),
			"xero_invoice_id": invoice_doc.get("xero_invoice_id") or _as_str(getattr(src, "xero_invoice_id", "")),
			"xero_invoice_number": invoice_doc.get("xero_invoice_number") or _as_str(getattr(src, "xero_invoice_number", "")),
			"items": invoice_doc.get("items")
			or [
				{"item_code": _as_str(r.item_code), "qty": float(r.qty or 0), "rate": float(r.rate or 0)}
				for r in (src.items or [])
			],
		}
	customer_name = _as_str(invoice_doc.get("customer"))
	if not customer_name:
		frappe.throw("Invoice customer is required for Xero sync.", frappe.ValidationError)
	contact_id = _as_str(frappe.db.get_value("Customer", customer_name, "xero_contact_id"))
	if not contact_id:
		frappe.throw(f"Customer {customer_name} is missing xero_contact_id; sync customer first.", frappe.ValidationError)

	items = invoice_doc.get("items") if isinstance(invoice_doc.get("items"), list) else []
	if not items:
		frappe.throw("Invoice has no items to sync.", frappe.ValidationError)
	line_items: list[dict[str, Any]] = []
	for row in items:
		if not isinstance(row, dict):
			continue
		qty = float(row.get("qty") or 1)
		rate = float(row.get("rate") or 0)
		item_code = _as_str(row.get("item_code")) or "Service"
		line_items.append({
			"Description": item_code,
			"Quantity": qty,
			"UnitAmount": rate,
			"AccountCode": "200",
		})
	if not line_items:
		frappe.throw("Invoice line mapping failed; no valid line items.", frappe.ValidationError)

	payload: dict[str, Any] = {
		"Type": "ACCREC",
		"Contact": {"ContactID": contact_id},
		"Date": _as_str(invoice_doc.get("posting_date")) or _as_str(frappe.utils.nowdate()),
		"DueDate": _as_str(invoice_doc.get("due_date")) or _as_str(invoice_doc.get("posting_date")) or _as_str(frappe.utils.nowdate()),
		"Status": "DRAFT",
		"LineItems": line_items,
	}
	xero_invoice_id = _as_str(invoice_doc.get("xero_invoice_id"))
	if xero_invoice_id:
		payload["InvoiceID"] = xero_invoice_id

	out = _xero_api_json(config, "PUT", "Invoices", {"Invoices": [payload]})
	rows = out.get("Invoices") if isinstance(out.get("Invoices"), list) else []
	return rows[0] if rows and isinstance(rows[0], dict) else {}


def _xero_push_payment(config: dict[str, Any], reference_name: str, document: dict[str, Any]) -> dict[str, Any]:
	payment_doc = document or {}
	if reference_name and frappe.db.exists("Payment Entry", reference_name):
		src = frappe.get_doc("Payment Entry", reference_name)
		payment_doc = {
			**payment_doc,
			"reference_no": payment_doc.get("reference_no") or _as_str(getattr(src, "reference_no", "")),
			"posting_date": payment_doc.get("posting_date") or _as_str(getattr(src, "posting_date", "")),
			"paid_amount": payment_doc.get("paid_amount") or float(getattr(src, "paid_amount", 0) or 0),
			"references": payment_doc.get("references")
			or [
				{
					"reference_doctype": _as_str(getattr(r, "reference_doctype", "")),
					"reference_name": _as_str(getattr(r, "reference_name", "")),
					"allocated_amount": float(getattr(r, "allocated_amount", 0) or 0),
				}
				for r in (getattr(src, "references", []) or [])
			],
		}
	refs = payment_doc.get("references") if isinstance(payment_doc.get("references"), list) else []
	first_ref = refs[0] if refs and isinstance(refs[0], dict) else {}
	invoice_name = _as_str(first_ref.get("reference_name"))
	if not invoice_name or not frappe.db.exists("Sales Invoice", invoice_name):
		frappe.throw("Payment push requires a linked Sales Invoice reference.", frappe.ValidationError)
	invoice_id = _as_str(frappe.db.get_value("Sales Invoice", invoice_name, "xero_invoice_id"))
	if not invoice_id:
		frappe.throw("Linked Sales Invoice is not mapped to Xero yet.", frappe.ValidationError)
	amount = float(first_ref.get("allocated_amount") or payment_doc.get("paid_amount") or 0)
	if amount <= 0:
		frappe.throw("Payment amount must be greater than zero.", frappe.ValidationError)
	payload = {
		"Invoice": {"InvoiceID": invoice_id},
		"Date": _as_str(payment_doc.get("posting_date")) or _as_str(frappe.utils.nowdate()),
		"Amount": amount,
		"Reference": _as_str(payment_doc.get("reference_no") or reference_name),
	}
	out = _xero_api_json(config, "PUT", "Payments", {"Payments": [payload]})
	rows = out.get("Payments") if isinstance(out.get("Payments"), list) else []
	return rows[0] if rows and isinstance(rows[0], dict) else {}


def _ensure_xero_sync_item() -> str:
	code = "XERO-SYNC-SERVICE"
	if frappe.db.exists("Item", code):
		return code
	item = frappe.new_doc("Item")
	item.item_code = code
	item.item_name = "Xero Imported Service"
	item.item_group = frappe.db.get_single_value("Stock Settings", "item_group") or "All Item Groups"
	item.stock_uom = "Nos"
	item.is_stock_item = 0
	item.include_item_in_manufacturing = 0
	item.flags.ignore_permissions = True
	item.insert(ignore_permissions=True)
	return code


def _ensure_xero_sync_item_for_line(line: dict[str, Any]) -> str:
	item_obj = line.get("Item") if isinstance(line.get("Item"), dict) else {}
	xero_item_id = _as_str(line.get("ItemID") or item_obj.get("ItemID")).strip()
	xero_item_code = _as_str(
		line.get("ItemCode")
		or line.get("Code")
		or item_obj.get("Code")
		or line.get("AccountCode")
	).strip()
	if xero_item_id and frappe.db.exists("Item", {"xero_item_id": xero_item_id}):
		return _as_str(frappe.db.get_value("Item", {"xero_item_id": xero_item_id}, "name"))
	if xero_item_code and frappe.db.exists("Item", {"xero_item_code": xero_item_code}):
		return _as_str(frappe.db.get_value("Item", {"xero_item_code": xero_item_code}, "name"))
	if xero_item_code and frappe.db.exists("Item", {"item_code": xero_item_code}):
		return _as_str(frappe.db.get_value("Item", {"item_code": xero_item_code}, "name"))

	source_code = _as_str(
		xero_item_code
	).strip()
	description = _as_str(line.get("Description")).strip()
	line_id = _as_str(line.get("LineItemID")).strip()
	if source_code:
		candidate = f"XERO-{source_code.upper()}"
	elif description:
		slug = re.sub(r"[^A-Za-z0-9]+", "-", description).strip("-").upper()
		candidate = f"XERO-{slug[:40]}" if slug else ""
	elif line_id:
		candidate = f"XERO-LINE-{line_id.replace('-', '')[:24].upper()}"
	else:
		candidate = ""
	if not candidate:
		signature = f"{_as_str(line.get('AccountCode'))}|{_as_str(line.get('Description'))}|{_as_str(line.get('Quantity'))}|{_as_str(line.get('UnitAmount'))}|{_as_str(line.get('LineAmount'))}"
		digest = hashlib.md5(signature.encode("utf-8")).hexdigest()[:12].upper()
		candidate = f"XERO-LINE-{digest}"
	code = candidate[:140]
	if frappe.db.exists("Item", code):
		return code

	item = frappe.new_doc("Item")
	item.item_code = code
	item.item_name = description[:140] or source_code[:140] or "Xero Imported Service"
	item.description = description or f"Imported from Xero ({source_code or 'service'})"
	item.item_group = frappe.db.get_single_value("Stock Settings", "item_group") or "All Item Groups"
	item.stock_uom = "Nos"
	item.is_stock_item = 0
	item.include_item_in_manufacturing = 0
	item.flags.ignore_permissions = True
	item.insert(ignore_permissions=True)
	return code


def _xero_invoice_lines_to_erp_items(invoice: dict[str, Any], fallback_total: float) -> list[dict[str, Any]]:
	line_items = invoice.get("LineItems")
	rows = line_items if isinstance(line_items, list) else []
	out: list[dict[str, Any]] = []
	for line in rows:
		if not isinstance(line, dict):
			continue
		qty = float(line.get("Quantity") or 1) or 1
		rate = float(line.get("UnitAmount") or 0)
		amount = float(line.get("LineAmount") or 0)
		if amount <= 0 and rate > 0:
			amount = float(rate * qty)
		if rate <= 0 and amount > 0:
			rate = amount / qty if qty else amount
		if amount <= 0:
			continue
		item_code = _ensure_xero_sync_item_for_line(line)
		description = _as_str(line.get("Description"))
		row = {
			"item_code": item_code,
			"qty": qty,
			"rate": rate,
			"amount": amount,
		}
		if description:
			row["description"] = description
		out.append(row)
	if out:
		return out
	item_code = _ensure_xero_sync_item()
	return [{"item_code": item_code, "qty": 1, "rate": fallback_total, "amount": fallback_total}]


def _default_bank_account(company: str) -> str:
	if company:
		row = frappe.db.sql(
			"""
			select name
			from `tabAccount`
			where company=%s and is_group=0 and (account_type='Bank' or account_type='Cash')
			order by account_type='Bank' desc, modified desc
			limit 1
			""",
			(company,),
			as_dict=True,
		)
		if row:
			return _as_str(row[0].get("name"))
	row = frappe.db.sql(
		"""
		select name
		from `tabAccount`
		where is_group=0 and (account_type='Bank' or account_type='Cash')
		order by account_type='Bank' desc, modified desc
		limit 1
		""",
		as_dict=True,
	)
	return _as_str(row[0].get("name")) if row else ""


def _upsert_payment_entry_from_xero_payment(payment: dict[str, Any]) -> str:
	payment_id = _as_str(payment.get("PaymentID"))
	if not payment_id:
		return ""
	if frappe.db.exists("Payment Entry", {"xero_payment_id": payment_id}):
		return _as_str(frappe.db.get_value("Payment Entry", {"xero_payment_id": payment_id}, "name"))

	invoice = payment.get("Invoice") if isinstance(payment.get("Invoice"), dict) else {}
	invoice_id = _as_str(invoice.get("InvoiceID"))
	invoice_name = _as_str(frappe.db.get_value("Sales Invoice", {"xero_invoice_id": invoice_id}, "name")) if invoice_id else ""
	if not invoice_name:
		return ""
	invoice_doc = frappe.get_doc("Sales Invoice", invoice_name)
	customer = _as_str(getattr(invoice_doc, "customer", ""))
	company = _as_str(getattr(invoice_doc, "company", ""))
	paid_from = _as_str(getattr(invoice_doc, "debit_to", ""))
	paid_to = _default_bank_account(company)
	if not customer or not paid_from or not paid_to:
		return ""

	amount = float(payment.get("Amount") or 0)
	if amount <= 0:
		return ""
	date_val = _as_str(payment.get("Date") or payment.get("DateString") or frappe.utils.nowdate())[:10]
	ref = _as_str(payment.get("Reference") or payment.get("PaymentID"))
	currency = _as_str(getattr(invoice_doc, "currency", "")) or _as_str(getattr(invoice_doc, "party_account_currency", "")) or "AUD"

	doc = frappe.new_doc("Payment Entry")
	doc.payment_type = "Receive"
	doc.party_type = "Customer"
	doc.party = customer
	doc.company = company
	doc.posting_date = date_val
	doc.paid_from = paid_from
	doc.paid_to = paid_to
	doc.paid_amount = amount
	doc.received_amount = amount
	doc.reference_no = ref[:140]
	doc.reference_date = date_val
	doc.mode_of_payment = frappe.db.get_value("Mode of Payment", {}, "name") or "Bank"
	doc.paid_from_account_currency = currency
	doc.paid_to_account_currency = currency
	doc.append(
		"references",
		{
			"reference_doctype": "Sales Invoice",
			"reference_name": invoice_name,
			"allocated_amount": amount,
			"due_date": _as_str(getattr(invoice_doc, "due_date", "")) or date_val,
			"total_amount": float(getattr(invoice_doc, "grand_total", amount) or amount),
			"outstanding_amount": float(getattr(invoice_doc, "outstanding_amount", amount) or amount),
		},
	)
	doc.xero_payment_id = payment_id
	doc.xero_payment_ref = ref
	doc.xero_last_synced_at = frappe.utils.now_datetime()
	doc.accounting_sync_status = "Synced"
	doc.accounting_last_synced_at = frappe.utils.now_datetime()
	doc.accounting_provider = "Xero"
	doc.accounting_external_id = payment_id
	doc.accounting_sync_error = ""
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	return _as_str(doc.name)


def _upsert_item_from_xero_item(item_row: dict[str, Any]) -> str:
	xero_item_id = _as_str(item_row.get("ItemID"))
	xero_item_code = _as_str(item_row.get("Code"))
	name = _as_str(item_row.get("Name")) or xero_item_code
	description = _as_str(item_row.get("Description"))
	sales_price = float(item_row.get("SalesDetails", {}).get("UnitPrice") or 0) if isinstance(item_row.get("SalesDetails"), dict) else 0.0
	if not xero_item_id and not xero_item_code:
		return ""

	item_name = ""
	if xero_item_id and frappe.db.exists("Item", {"xero_item_id": xero_item_id}):
		item_name = _as_str(frappe.db.get_value("Item", {"xero_item_id": xero_item_id}, "name"))
	elif xero_item_code and frappe.db.exists("Item", xero_item_code):
		item_name = xero_item_code
	elif xero_item_code and frappe.db.exists("Item", {"item_code": xero_item_code}):
		item_name = _as_str(frappe.db.get_value("Item", {"item_code": xero_item_code}, "name"))

	if item_name:
		doc = frappe.get_doc("Item", item_name)
	else:
		doc = frappe.new_doc("Item")
		doc.item_code = xero_item_code or f"XERO-ITEM-{xero_item_id[:12]}"
		doc.item_name = name or doc.item_code
		doc.item_group = frappe.db.get_single_value("Stock Settings", "item_group") or "All Item Groups"
		doc.stock_uom = "Nos"
		doc.is_stock_item = 0
		doc.include_item_in_manufacturing = 0

	if name:
		doc.item_name = name
	if description:
		doc.description = description
	if sales_price > 0:
		doc.standard_rate = sales_price
	doc.xero_item_id = xero_item_id
	doc.xero_item_code = xero_item_code
	doc.xero_last_synced_at = frappe.utils.now_datetime()
	doc.accounting_sync_status = "Synced"
	doc.accounting_last_synced_at = frappe.utils.now_datetime()
	doc.accounting_provider = "Xero"
	doc.accounting_external_id = xero_item_id or xero_item_code
	doc.accounting_sync_error = ""
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)
	return _as_str(doc.name)


def _upsert_sales_invoice_from_xero_invoice(invoice: dict[str, Any]) -> str:
	invoice_id = _as_str(invoice.get("InvoiceID"))
	invoice_number = _as_str(invoice.get("InvoiceNumber"))
	contact = invoice.get("Contact") if isinstance(invoice.get("Contact"), dict) else {}
	contact_id = _as_str(contact.get("ContactID"))
	customer = ""
	if contact_id and frappe.db.exists("Customer", {"xero_contact_id": contact_id}):
		customer = _as_str(frappe.db.get_value("Customer", {"xero_contact_id": contact_id}, "name"))
	if not customer:
		customer = _upsert_customer_from_xero_contact(contact if isinstance(contact, dict) else {})
	if not customer:
		return ""

	doc_name = ""
	if invoice_id and frappe.db.exists("Sales Invoice", {"xero_invoice_id": invoice_id}):
		doc_name = _as_str(frappe.db.get_value("Sales Invoice", {"xero_invoice_id": invoice_id}, "name"))
	elif invoice_number and frappe.db.exists("Sales Invoice", {"bill_no": invoice_number}):
		doc_name = _as_str(frappe.db.get_value("Sales Invoice", {"bill_no": invoice_number}, "name"))

	total = float(invoice.get("Total") or 0)
	date_val = _as_str(invoice.get("DateString") or invoice.get("Date") or frappe.utils.nowdate())[:10]
	due_val = _as_str(invoice.get("DueDateString") or invoice.get("DueDate") or date_val)[:10]
	erp_items = _xero_invoice_lines_to_erp_items(invoice, total)

	if doc_name:
		doc = frappe.get_doc("Sales Invoice", doc_name)
		if int(doc.docstatus or 0) != 0:
			return _as_str(doc.name)
		doc.customer = customer
		doc.bill_no = invoice_number or doc.bill_no
		doc.posting_date = date_val
		doc.due_date = due_val
		doc.xero_invoice_id = invoice_id
		doc.xero_invoice_number = invoice_number
		doc.xero_last_synced_at = frappe.utils.now_datetime()
		doc.accounting_sync_status = "Synced"
		doc.accounting_last_synced_at = frappe.utils.now_datetime()
		doc.accounting_provider = "Xero"
		doc.accounting_external_id = invoice_id
		doc.accounting_sync_error = ""
		doc.items = []
		for row in erp_items:
			doc.append("items", row)
		doc.flags.ignore_permissions = True
		doc.save(ignore_permissions=True)
		return _as_str(doc.name)

	doc = frappe.new_doc("Sales Invoice")
	doc.customer = customer
	doc.bill_no = invoice_number
	doc.posting_date = date_val
	doc.due_date = due_val
	doc.xero_invoice_id = invoice_id
	doc.xero_invoice_number = invoice_number
	doc.xero_last_synced_at = frappe.utils.now_datetime()
	doc.accounting_sync_status = "Synced"
	doc.accounting_last_synced_at = frappe.utils.now_datetime()
	doc.accounting_provider = "Xero"
	doc.accounting_external_id = invoice_id
	doc.accounting_sync_error = ""
	for row in erp_items:
		doc.append("items", row)
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	return _as_str(doc.name)


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
		if row_place_id:
			return row_place_id == in_place_id
		# If existing row has no place_id yet, still allow strong textual/location match
		# so we don't create duplicate addresses/properties for the same site.
		# place_id can be backfilled later.
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

	# Preserve existing credential/endpoint values when caller omits them
	# (tenant-safe save payloads intentionally exclude sensitive fields).
	def _pick_str(*keys: str, fallback: str = "") -> str:
		for k in keys:
			if k in kwargs and kwargs.get(k) is not None:
				return _as_str(kwargs.get(k))
		return fallback

	current.update(
		{
			"provider": provider,
			"enabled": _as_bool(kwargs.get("enabled")),
			"name": _as_str(kwargs.get("name")) or provider,
			"baseUrl": _pick_str("base_url", "baseUrl", fallback=_as_str(current.get("baseUrl"))),
			"authUrl": _pick_str("auth_url", "authUrl", fallback=_as_str(current.get("authUrl"))),
			"tokenUrl": _pick_str("token_url", "tokenUrl", fallback=_as_str(current.get("tokenUrl"))),
			"clientId": _pick_str("client_id", "clientId", fallback=_as_str(current.get("clientId"))),
			"clientSecret": _pick_str("client_secret", "clientSecret", fallback=_as_str(current.get("clientSecret"))),
			"tenantId": _pick_str("tenant_id", "tenantId", fallback=_as_str(current.get("tenantId"))),
			"scopes": _pick_str("scopes", fallback=_as_str(current.get("scopes"))),
			"webhookSecret": _pick_str("webhook_secret", "webhookSecret", fallback=_as_str(current.get("webhookSecret"))),
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


@frappe.whitelist()
def _xero_site_config_credentials() -> tuple[str, str]:
	client_id = _as_str(frappe.conf.get("firtrackpro_xero_client_id") or frappe.conf.get("xero_client_id"))
	client_secret = _as_str(frappe.conf.get("firtrackpro_xero_client_secret") or frappe.conf.get("xero_client_secret"))
	return client_id, client_secret


def _xero_apply_site_config_credentials(row: dict[str, Any]) -> tuple[dict[str, Any], bool]:
	client_id, client_secret = _xero_site_config_credentials()
	changed = False
	if client_id and _as_str(row.get("clientId")) != client_id:
		row["clientId"] = client_id
		changed = True
	if client_secret and _as_str(row.get("clientSecret")) != client_secret:
		row["clientSecret"] = client_secret
		changed = True
	return row, changed


def _quickbooks_site_config_credentials() -> tuple[str, str]:
	client_id = _as_str(
		frappe.conf.get("firtrackpro_quickbooks_client_id")
		or frappe.conf.get("quickbooks_client_id")
		or frappe.conf.get("firtrackpro_intuit_client_id")
		or frappe.conf.get("intuit_client_id")
	)
	client_secret = _as_str(
		frappe.conf.get("firtrackpro_quickbooks_client_secret")
		or frappe.conf.get("quickbooks_client_secret")
		or frappe.conf.get("firtrackpro_intuit_client_secret")
		or frappe.conf.get("intuit_client_secret")
	)
	return client_id, client_secret


def _quickbooks_apply_site_config_credentials(row: dict[str, Any]) -> tuple[dict[str, Any], bool]:
	client_id, client_secret = _quickbooks_site_config_credentials()
	changed = False
	if client_id and _as_str(row.get("clientId")) != client_id:
		row["clientId"] = client_id
		changed = True
	if client_secret and _as_str(row.get("clientSecret")) != client_secret:
		row["clientSecret"] = client_secret
		changed = True
	return row, changed

def _xero_is_unauthorized_client(resp: Any) -> bool:
	try:
		payload = resp.json() if hasattr(resp, "json") else {}
	except Exception:
		payload = {}
	error = _as_str(payload.get("error"))
	text = _as_str(getattr(resp, "text", ""))
	return error == "unauthorized_client" or "unauthorized_client" in text.lower()


def _xero_state_secret() -> str:
	return _as_str(_firelink_bridge_token()) or _as_str(frappe.local.site) or "firetrack-xero"


def _xero_build_federated_state(site_host: str) -> str:
	host = _normalize_site_host(site_host)
	if not host:
		return frappe.generate_hash(length=28)
	payload = {
		"v": 1,
		"h": host,
		"n": frappe.generate_hash(length=10),
		"t": int(datetime.now(timezone.utc).timestamp()),
	}
	raw = json.dumps(payload, separators=(",", ":"), sort_keys=True)
	raw_b64 = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8").rstrip("=")
	sig = hmac.new(_xero_state_secret().encode("utf-8"), raw_b64.encode("utf-8"), hashlib.sha256).hexdigest()[:24]
	return f"ftx1.{raw_b64}.{sig}"


def _xero_parse_federated_state(state: str) -> str:
	value = _as_str(state)
	if not value.startswith("ftx1."):
		return ""
	parts = value.split(".")
	if len(parts) != 3:
		return ""
	_, raw_b64, sig = parts
	expected = hmac.new(_xero_state_secret().encode("utf-8"), raw_b64.encode("utf-8"), hashlib.sha256).hexdigest()[:24]
	if not hmac.compare_digest(expected, sig):
		return ""
	try:
		padded = raw_b64 + "=" * ((4 - len(raw_b64) % 4) % 4)
		decoded = base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
		payload = json.loads(decoded)
	except Exception:
		return ""
	host = _normalize_site_host((payload or {}).get("h"))
	return host


def xero_receive_tokens_local(**kwargs):
	target_host = _normalize_site_host(kwargs.get("target_host") or getattr(frappe.local, "site", ""))
	if not target_host:
		return {"ok": False, "message": "target_host is required."}
	row = _integration_record("Xero")
	row["clientId"] = _as_str(kwargs.get("client_id") or row.get("clientId"))
	row["clientSecret"] = _as_str(kwargs.get("client_secret") or row.get("clientSecret"))
	row["authUrl"] = _as_str(kwargs.get("auth_url") or row.get("authUrl") or PROVIDER_DEFAULTS["Xero"].get("authUrl"))
	row["tokenUrl"] = _as_str(kwargs.get("token_url") or row.get("tokenUrl") or PROVIDER_DEFAULTS["Xero"].get("tokenUrl"))
	row["scopes"] = _as_str(kwargs.get("scopes") or row.get("scopes") or PROVIDER_DEFAULTS["Xero"].get("scopes"))
	row["webhookSecret"] = _as_str(kwargs.get("webhook_secret") or row.get("webhookSecret"))
	row["xeroAccessToken"] = _as_str(kwargs.get("xero_access_token"))
	row["xeroRefreshToken"] = _as_str(kwargs.get("xero_refresh_token"))
	row["xeroTokenExpiresAt"] = _as_str(kwargs.get("xero_token_expires_at"))
	row["xeroConnectedAt"] = _as_str(kwargs.get("xero_connected_at")) or _utc_iso_now()
	row["xeroState"] = ""
	connections = kwargs.get("xero_connections")
	if isinstance(connections, list):
		row["xeroConnectionsJson"] = json.dumps(connections)
		if connections and not _as_str(row.get("tenantId")):
			first = connections[0] if isinstance(connections[0], dict) else {}
			row["tenantId"] = _as_str(first.get("tenantId"))
	_persist_integration_record("Xero", row)
	return {"ok": True, "site_host": target_host}


def _xero_push_tokens_to_site(target_host: str, row: dict[str, Any], connections: list[dict[str, Any]]) -> dict[str, Any]:
	host = _normalize_site_host(target_host)
	if not host:
		return {"ok": False, "message": "target_host is required"}
	kwargs_payload = {
		"target_host": host,
		"client_id": _as_str(row.get("clientId")),
		"client_secret": _as_str(row.get("clientSecret")),
		"auth_url": _as_str(row.get("authUrl")),
		"token_url": _as_str(row.get("tokenUrl")),
		"scopes": _as_str(row.get("scopes")),
		"webhook_secret": _as_str(row.get("webhookSecret")),
		"xero_access_token": _as_str(row.get("xeroAccessToken")),
		"xero_refresh_token": _as_str(row.get("xeroRefreshToken")),
		"xero_token_expires_at": _as_str(row.get("xeroTokenExpiresAt")),
		"xero_connected_at": _as_str(row.get("xeroConnectedAt")),
		"xero_connections": connections,
	}
	try:
		res = subprocess.run(
			[
				"bench",
				"--site",
				host,
				"execute",
				"firtrackpro.api.integrations.xero_receive_tokens_local",
				"--kwargs",
				json.dumps(kwargs_payload),
			],
			check=False,
			text=True,
			capture_output=True,
			timeout=180,
			cwd=_sites_root_path(),
		)
	except Exception as exc:
		return {"ok": False, "message": f"token push failed to start: {exc}"}
	if int(res.returncode or 0) != 0:
		detail = ((res.stdout or "") + "\n" + (res.stderr or "")).strip()
		if len(detail) > 800:
			detail = detail[-800:]
		return {"ok": False, "message": f"token push failed for {host}", "details": detail}
	return {"ok": True, "site_host": host}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def firelink_xero_oauth_start_bridge(**kwargs):
	if not _is_valid_bridge_call():
		frappe.throw("Bridge token or approved firetrackpro origin is required", frappe.PermissionError)
	target_host = _normalize_site_host(kwargs.get("site_host"))
	if not target_host:
		frappe.throw("site_host is required", frappe.ValidationError)
	if not _is_firelink_local_site():
		return _firelink_remote_bridge_call(
			"/api/method/firtrackpro.api.integrations.firelink_xero_oauth_start_bridge",
			_remote_bridge_payload({"site_host": target_host}),
		)
	row = _integration_record("Xero")
	client_id = _as_str(row.get("clientId"))
	client_secret = _as_str(row.get("clientSecret"))
	auth_url = _as_str(row.get("authUrl")) or _as_str(PROVIDER_DEFAULTS["Xero"].get("authUrl"))
	scopes = _as_str(row.get("scopes")) or _as_str(PROVIDER_DEFAULTS["Xero"].get("scopes"))
	if not client_id or not client_secret:
		frappe.throw("Xero Client ID and Client Secret are required on FireLink.", frappe.ValidationError)
	state = _xero_build_federated_state(target_host)
	row["xeroState"] = state
	_persist_integration_record("Xero", row)
	params = {
		"response_type": "code",
		"client_id": client_id,
		"redirect_uri": _xero_redirect_uri(row),
		"scope": scopes,
		"state": state,
	}
	return {"ok": True, "authorize_url": f"{auth_url}?{urlencode(params)}", "state": state, "redirect_uri": _xero_redirect_uri(row), "target_site": target_host}

def xero_oauth_start(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	row = _integration_record("Xero")
	client_id = _as_str(kwargs.get("client_id") or kwargs.get("clientId") or row.get("clientId"))
	client_secret = _as_str(kwargs.get("client_secret") or kwargs.get("clientSecret") or row.get("clientSecret"))
	auth_url = _as_str(kwargs.get("auth_url") or kwargs.get("authUrl") or row.get("authUrl")) or _as_str(
		PROVIDER_DEFAULTS["Xero"].get("authUrl")
	)
	scopes = _as_str(kwargs.get("scopes") or row.get("scopes")) or _as_str(PROVIDER_DEFAULTS["Xero"].get("scopes"))
	if not client_id or not client_secret:
		frappe.throw("Xero Client ID and Client Secret are required.", frappe.ValidationError)
	if not auth_url:
		frappe.throw("Xero Auth URL is required.", frappe.ValidationError)

	state = frappe.generate_hash(length=28)
	row["clientId"] = client_id
	row["clientSecret"] = client_secret
	row["authUrl"] = auth_url
	row["scopes"] = scopes
	row["xeroState"] = state
	_persist_integration_record("Xero", row)

	params = {
		"response_type": "code",
		"client_id": client_id,
		"redirect_uri": _xero_redirect_uri(row),
		"scope": scopes,
		"state": state,
	}
	return {"ok": True, "authorize_url": f"{auth_url}?{urlencode(params)}", "state": state, "redirect_uri": _xero_redirect_uri(row)}


@frappe.whitelist(allow_guest=True)
def xero_oauth_callback(**kwargs):
	code = _as_str(kwargs.get("code"))
	state = _as_str(kwargs.get("state"))
	error = _as_str(kwargs.get("error"))
	error_description = _as_str(kwargs.get("error_description"))
	target_host = _xero_parse_federated_state(state)
	_ensure_customer_xero_fields()
	_ensure_supplier_xero_fields()
	_ensure_sales_invoice_xero_fields()
	if error:
		frappe.local.response["type"] = "redirect"
		if target_host and target_host != _as_str(getattr(frappe.local, "site", "")):
			frappe.local.response["location"] = f"https://{target_host}/portal/config/integrations?xero=error&message={quote(error_description or error)}"
		else:
			frappe.local.response["location"] = f"/portal/config/integrations?xero=error&message={quote(error_description or error)}"
		return

	row = _integration_record("Xero")
	expected_state = _as_str(row.get("xeroState"))
	if not code:
		frappe.throw("Missing Xero authorization code.", frappe.ValidationError)
	if expected_state and not target_host and state != expected_state:
		frappe.throw("Invalid Xero OAuth state.", frappe.PermissionError)

	client_id = _as_str(row.get("clientId"))
	client_secret = _as_str(row.get("clientSecret"))
	token_url = _as_str(row.get("tokenUrl")) or _as_str(PROVIDER_DEFAULTS["Xero"].get("tokenUrl"))
	if not client_id or not client_secret or not token_url:
		frappe.throw("Xero Client ID/Secret and Token URL must be configured before OAuth callback.", frappe.ValidationError)
	if requests is None:
		frappe.throw("Xero callback unavailable (requests library missing).")

	headers = {
		"Authorization": f"Basic {_xero_basic_auth(client_id, client_secret)}",
		"Content-Type": "application/x-www-form-urlencoded",
		"Accept": "application/json",
	}
	form = {"grant_type": "authorization_code", "code": code, "redirect_uri": _xero_redirect_uri(row)}
	resp = requests.post(token_url, headers=headers, data=form, timeout=20)
	if not resp.ok:
		detail = _as_str(resp.text)
		frappe.throw(f"Xero token exchange failed ({resp.status_code}): {detail}", frappe.ValidationError)
	data = resp.json() if hasattr(resp, "json") else {}
	access_token = _as_str(data.get("access_token"))
	refresh_token = _as_str(data.get("refresh_token"))
	expires_in = _as_int(data.get("expires_in"), 1800)
	if not access_token:
		frappe.throw("Xero token exchange did not return access_token.", frappe.ValidationError)
	row["xeroAccessToken"] = access_token
	row["xeroRefreshToken"] = refresh_token
	row["xeroTokenExpiresAt"] = datetime.fromtimestamp(
		datetime.now(timezone.utc).timestamp() + expires_in, tz=timezone.utc
	).isoformat()
	row["xeroConnectedAt"] = _utc_iso_now()
	row["xeroState"] = ""

	connections = _xero_fetch_connections(row)
	if not connections:
		frappe.local.response["type"] = "redirect"
		frappe.local.response["location"] = "/portal/config/integrations?xero=error&message=No%20Xero%20organization%20connection%20was%20returned."
		return
	row["xeroConnectionsJson"] = json.dumps(connections)
	first = connections[0] if isinstance(connections[0], dict) else {}
	row["tenantId"] = _as_str(first.get("tenantId"))
	row["enabled"] = True
	_persist_integration_record("Xero", row)

	if target_host and target_host != _as_str(getattr(frappe.local, "site", "")):
		push = _xero_push_tokens_to_site(target_host, row, connections)
		if not _as_bool(push.get("ok")):
			msg = _as_str(push.get("message")) or "Failed to save Xero connection to target tenant."
			details = _as_str(push.get("details"))
			if details:
				msg = f"{msg} {details}"
			frappe.local.response["type"] = "redirect"
			frappe.local.response["location"] = f"https://{target_host}/portal/config/integrations?xero=error&message={quote(msg)}"
			return
		frappe.local.response["type"] = "redirect"
		frappe.local.response["location"] = f"https://{target_host}/portal/config/integrations?xero=connected"
		return

	frappe.local.response["type"] = "redirect"
	frappe.local.response["location"] = "/portal/config/integrations?xero=connected"
@frappe.whitelist(methods=["POST", "GET"])
def xero_disconnect(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	row = _integration_record("Xero")
	row = _xero_apply_site_config_credentials(row)[0]
	is_firelink_site = _is_firelink_local_site()
	force_revoke = _as_bool(kwargs.get("force_revoke") or kwargs.get("forceRevoke"))
	skip_remote_revoke = _as_bool(kwargs.get("skip_remote_revoke") or kwargs.get("skipRemoteRevoke"))
	# Default behavior is now full disconnect (remote revoke included), including on FireLink.
	# Pass skip_remote_revoke=1 only when you intentionally want local-token clear without Xero-side unlink.
	should_revoke_remote = (not skip_remote_revoke) and ((not is_firelink_site) or force_revoke or is_firelink_site)
	revoke_result = _xero_remote_disconnect(row) if should_revoke_remote else {
		"ok": True,
		"message": "Skipped remote revoke by request.",
	}
	row["xeroAccessToken"] = ""
	row["xeroRefreshToken"] = ""
	row["xeroTokenExpiresAt"] = ""
	row["xeroConnectedAt"] = ""
	row["xeroState"] = ""
	row["xeroConnectionsJson"] = "[]"
	row["tenantId"] = ""
	row["enabled"] = False
	_persist_integration_record("Xero", row)
	msg = "Xero disconnected."
	ok = True
	if isinstance(revoke_result, dict):
		ok = _as_bool(revoke_result.get("ok")) if "ok" in revoke_result else True
		remote_msg = _as_str(revoke_result.get("message"))
		if remote_msg:
			msg = f"{msg} {remote_msg}"
	return {"ok": ok, "message": msg.strip()}


def _quickbooks_redirect_uri(row: dict[str, Any] | None = None) -> str:
	row = row or {}
	candidates = [
		_as_str(row.get("quickbooksRedirectUri")),
		_as_str(row.get("redirectUri")),
		_as_str(frappe.conf.get("quickbooks_oauth_redirect_uri")),
		_as_str(frappe.conf.get("firtrackpro_quickbooks_oauth_redirect_uri")),
	]
	for candidate in candidates:
		if candidate:
			return candidate.rstrip("/")
	host_name = _as_str(frappe.conf.get("host_name")).rstrip("/")
	if host_name:
		return f"{host_name}/api/method/firtrackpro.api.integrations.quickbooks_oauth_callback"
	base = _as_str(frappe.utils.get_url()).rstrip("/")
	return f"{base}/api/method/firtrackpro.api.integrations.quickbooks_oauth_callback"


def _quickbooks_state_secret() -> str:
	return _as_str(_firelink_bridge_token()) or _as_str(frappe.local.site) or "firetrack-quickbooks"


def _quickbooks_build_federated_state(site_host: str) -> str:
	host = _normalize_site_host(site_host)
	if not host:
		return frappe.generate_hash(length=28)
	payload = {
		"v": 1,
		"h": host,
		"n": frappe.generate_hash(length=10),
		"t": int(datetime.now(timezone.utc).timestamp()),
	}
	raw = json.dumps(payload, separators=(",", ":"), sort_keys=True)
	raw_b64 = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8").rstrip("=")
	sig = hmac.new(_quickbooks_state_secret().encode("utf-8"), raw_b64.encode("utf-8"), hashlib.sha256).hexdigest()[:24]
	return f"ftq1.{raw_b64}.{sig}"


def _quickbooks_parse_federated_state(state: str) -> str:
	value = _as_str(state)
	if not value.startswith("ftq1."):
		return ""
	parts = value.split(".")
	if len(parts) != 3:
		return ""
	_, raw_b64, sig = parts
	expected = hmac.new(_quickbooks_state_secret().encode("utf-8"), raw_b64.encode("utf-8"), hashlib.sha256).hexdigest()[:24]
	if not hmac.compare_digest(expected, sig):
		return ""
	try:
		padded = raw_b64 + "=" * ((4 - len(raw_b64) % 4) % 4)
		decoded = base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
		payload = json.loads(decoded)
	except Exception:
		return ""
	return _normalize_site_host((payload or {}).get("h"))


def quickbooks_receive_tokens_local(**kwargs):
	target_host = _normalize_site_host(kwargs.get("target_host") or getattr(frappe.local, "site", ""))
	if not target_host:
		return {"ok": False, "message": "target_host is required."}
	row = _integration_record("QuickBooks")
	row["clientId"] = _as_str(kwargs.get("client_id") or row.get("clientId"))
	row["clientSecret"] = _as_str(kwargs.get("client_secret") or row.get("clientSecret"))
	row["baseUrl"] = _as_str(kwargs.get("base_url") or row.get("baseUrl") or PROVIDER_DEFAULTS["QuickBooks"].get("baseUrl"))
	row["authUrl"] = _as_str(kwargs.get("auth_url") or row.get("authUrl") or PROVIDER_DEFAULTS["QuickBooks"].get("authUrl"))
	row["tokenUrl"] = _as_str(kwargs.get("token_url") or row.get("tokenUrl") or PROVIDER_DEFAULTS["QuickBooks"].get("tokenUrl"))
	row["scopes"] = _as_str(kwargs.get("scopes") or row.get("scopes") or PROVIDER_DEFAULTS["QuickBooks"].get("scopes"))
	if _as_str(kwargs.get("webhook_secret")):
		row["webhookSecret"] = _as_str(kwargs.get("webhook_secret"))
	row["quickbooksAccessToken"] = _as_str(kwargs.get("quickbooks_access_token"))
	row["quickbooksRefreshToken"] = _as_str(kwargs.get("quickbooks_refresh_token"))
	row["quickbooksTokenExpiresAt"] = _as_str(kwargs.get("quickbooks_token_expires_at"))
	row["quickbooksConnectedAt"] = _as_str(kwargs.get("quickbooks_connected_at")) or _utc_iso_now()
	row["quickbooksState"] = ""
	row["quickbooksRealmId"] = _as_str(kwargs.get("realm_id") or kwargs.get("quickbooks_realm_id"))
	if _as_str(row.get("quickbooksRealmId")):
		row["tenantId"] = _as_str(row.get("quickbooksRealmId"))
	row["enabled"] = True
	_persist_integration_record("QuickBooks", row)
	return {"ok": True, "site_host": target_host}


def _quickbooks_push_tokens_to_site(target_host: str, row: dict[str, Any], realm_id: str) -> dict[str, Any]:
	host = _normalize_site_host(target_host)
	if not host:
		return {"ok": False, "message": "target_host is required"}
	kwargs_payload = {
		"target_host": host,
		"client_id": _as_str(row.get("clientId")),
		"client_secret": _as_str(row.get("clientSecret")),
		"base_url": _as_str(row.get("baseUrl")),
		"auth_url": _as_str(row.get("authUrl")),
		"token_url": _as_str(row.get("tokenUrl")),
		"scopes": _as_str(row.get("scopes")),
		"webhook_secret": _as_str(row.get("webhookSecret")),
		"quickbooks_access_token": _as_str(row.get("quickbooksAccessToken")),
		"quickbooks_refresh_token": _as_str(row.get("quickbooksRefreshToken")),
		"quickbooks_token_expires_at": _as_str(row.get("quickbooksTokenExpiresAt")),
		"quickbooks_connected_at": _as_str(row.get("quickbooksConnectedAt")),
		"quickbooks_realm_id": _as_str(realm_id),
	}
	try:
		res = subprocess.run(
			[
				"bench",
				"--site",
				host,
				"execute",
				"firtrackpro.api.integrations.quickbooks_receive_tokens_local",
				"--kwargs",
				json.dumps(kwargs_payload),
			],
			check=False,
			text=True,
			capture_output=True,
			timeout=180,
			cwd=_sites_root_path(),
		)
	except Exception as exc:
		return {"ok": False, "message": f"token push failed to start: {exc}"}
	if int(res.returncode or 0) != 0:
		detail = ((res.stdout or "") + "\n" + (res.stderr or "")).strip()
		if len(detail) > 800:
			detail = detail[-800:]
		return {"ok": False, "message": f"token push failed for {host}", "details": detail}
	return {"ok": True, "site_host": host}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def firelink_quickbooks_oauth_start_bridge(**kwargs):
	if not _is_valid_bridge_call():
		frappe.throw("Bridge token or approved firetrackpro origin is required", frappe.PermissionError)
	target_host = _normalize_site_host(kwargs.get("site_host"))
	if not target_host:
		frappe.throw("site_host is required", frappe.ValidationError)
	if not _is_firelink_local_site():
		return _firelink_remote_bridge_call(
			"/api/method/firtrackpro.api.integrations.firelink_quickbooks_oauth_start_bridge",
			_remote_bridge_payload({"site_host": target_host}),
		)
	row = _integration_record("QuickBooks")
	client_id = _as_str(row.get("clientId"))
	client_secret = _as_str(row.get("clientSecret"))
	auth_url = _as_str(row.get("authUrl")) or _as_str(PROVIDER_DEFAULTS["QuickBooks"].get("authUrl"))
	scopes = _as_str(row.get("scopes")) or _as_str(PROVIDER_DEFAULTS["QuickBooks"].get("scopes"))
	if not client_id or not client_secret:
		frappe.throw("QuickBooks Client ID and Client Secret are required on FireLink.", frappe.ValidationError)
	state = _quickbooks_build_federated_state(target_host)
	row["quickbooksState"] = state
	_persist_integration_record("QuickBooks", row)
	params = {
		"response_type": "code",
		"client_id": client_id,
		"redirect_uri": _quickbooks_redirect_uri(row),
		"scope": scopes,
		"state": state,
	}
	return {"ok": True, "authorize_url": f"{auth_url}?{urlencode(params)}", "state": state, "redirect_uri": _quickbooks_redirect_uri(row), "target_site": target_host}

def quickbooks_oauth_start(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	row = _integration_record("QuickBooks")
	client_id = _as_str(kwargs.get("client_id") or kwargs.get("clientId") or row.get("clientId"))
	client_secret = _as_str(kwargs.get("client_secret") or kwargs.get("clientSecret") or row.get("clientSecret"))
	auth_url = _as_str(kwargs.get("auth_url") or kwargs.get("authUrl") or row.get("authUrl")) or _as_str(
		PROVIDER_DEFAULTS["QuickBooks"].get("authUrl")
	)
	scopes = _as_str(kwargs.get("scopes") or row.get("scopes")) or _as_str(PROVIDER_DEFAULTS["QuickBooks"].get("scopes"))
	if not client_id or not client_secret:
		frappe.throw("QuickBooks Client ID and Client Secret are required.", frappe.ValidationError)
	if not auth_url:
		frappe.throw("QuickBooks Auth URL is required.", frappe.ValidationError)
	state = frappe.generate_hash(length=28)
	row["clientId"] = client_id
	row["clientSecret"] = client_secret
	row["authUrl"] = auth_url
	row["scopes"] = scopes
	row["quickbooksState"] = state
	_persist_integration_record("QuickBooks", row)
	params = {
		"response_type": "code",
		"client_id": client_id,
		"redirect_uri": _quickbooks_redirect_uri(row),
		"scope": scopes,
		"state": state,
	}
	return {"ok": True, "authorize_url": f"{auth_url}?{urlencode(params)}", "state": state, "redirect_uri": _quickbooks_redirect_uri(row)}


@frappe.whitelist(allow_guest=True)
def quickbooks_oauth_callback(**kwargs):
	code = _as_str(kwargs.get("code"))
	state = _as_str(kwargs.get("state"))
	realm_id = _as_str(kwargs.get("realmId") or kwargs.get("realm_id"))
	error = _as_str(kwargs.get("error"))
	error_description = _as_str(kwargs.get("error_description"))
	target_host = _quickbooks_parse_federated_state(state)
	if error:
		frappe.local.response["type"] = "redirect"
		if target_host and target_host != _as_str(getattr(frappe.local, "site", "")):
			frappe.local.response["location"] = f"https://{target_host}/portal/config/integrations?quickbooks=error&message={quote(error_description or error)}"
		else:
			frappe.local.response["location"] = f"/portal/config/integrations?quickbooks=error&message={quote(error_description or error)}"
		return
	row = _integration_record("QuickBooks")
	expected_state = _as_str(row.get("quickbooksState"))
	if not code:
		frappe.throw("Missing QuickBooks authorization code.", frappe.ValidationError)
	if expected_state and not target_host and state != expected_state:
		frappe.throw("Invalid QuickBooks OAuth state.", frappe.PermissionError)
	client_id = _as_str(row.get("clientId"))
	client_secret = _as_str(row.get("clientSecret"))
	token_url = _as_str(row.get("tokenUrl")) or _as_str(PROVIDER_DEFAULTS["QuickBooks"].get("tokenUrl"))
	if not client_id or not client_secret or not token_url:
		frappe.throw("QuickBooks Client ID/Secret and Token URL must be configured before OAuth callback.", frappe.ValidationError)
	if requests is None:
		frappe.throw("QuickBooks callback unavailable (requests library missing).")
	headers = {
		"Authorization": f"Basic {_xero_basic_auth(client_id, client_secret)}",
		"Content-Type": "application/x-www-form-urlencoded",
		"Accept": "application/json",
	}
	form = {"grant_type": "authorization_code", "code": code, "redirect_uri": _quickbooks_redirect_uri(row)}
	resp = requests.post(token_url, headers=headers, data=form, timeout=20)
	if not resp.ok:
		detail = _as_str(resp.text)
		frappe.throw(f"QuickBooks token exchange failed ({resp.status_code}): {detail}", frappe.ValidationError)
	data = resp.json() if hasattr(resp, "json") else {}
	access_token = _as_str(data.get("access_token"))
	refresh_token = _as_str(data.get("refresh_token"))
	expires_in = _as_int(data.get("expires_in"), 3600)
	if not access_token:
		frappe.throw("QuickBooks token exchange did not return access_token.", frappe.ValidationError)
	row["quickbooksAccessToken"] = access_token
	row["quickbooksRefreshToken"] = refresh_token
	row["quickbooksTokenExpiresAt"] = datetime.fromtimestamp(
		datetime.now(timezone.utc).timestamp() + expires_in, tz=timezone.utc
	).isoformat()
	row["quickbooksConnectedAt"] = _utc_iso_now()
	row["quickbooksState"] = ""
	row["quickbooksRealmId"] = realm_id
	if realm_id:
		row["tenantId"] = realm_id
	row["enabled"] = True
	_persist_integration_record("QuickBooks", row)
	if target_host and target_host != _as_str(getattr(frappe.local, "site", "")):
		push = _quickbooks_push_tokens_to_site(target_host, row, realm_id)
		if not _as_bool(push.get("ok")):
			msg = _as_str(push.get("message")) or "Failed to save QuickBooks connection to target tenant."
			details = _as_str(push.get("details"))
			if details:
				msg = f"{msg} {details}"
			frappe.local.response["type"] = "redirect"
			frappe.local.response["location"] = f"https://{target_host}/portal/config/integrations?quickbooks=error&message={quote(msg)}"
			return
		frappe.local.response["type"] = "redirect"
		frappe.local.response["location"] = f"https://{target_host}/portal/config/integrations?quickbooks=connected"
		return
	frappe.local.response["type"] = "redirect"
	frappe.local.response["location"] = "/portal/config/integrations?quickbooks=connected"


def _quickbooks_remote_disconnect(config: dict[str, Any]) -> dict[str, Any]:
	if requests is None:
		return {"ok": False, "message": "Requests library missing; skipped remote revoke."}
	token = _as_str(config.get("quickbooksRefreshToken")) or _as_str(config.get("quickbooksAccessToken"))
	client_id = _as_str(config.get("clientId"))
	client_secret = _as_str(config.get("clientSecret"))
	if not token or not client_id or not client_secret:
		return {"ok": True, "message": "No QuickBooks token to revoke."}
	try:
		resp = requests.post(
			"https://developer.api.intuit.com/v2/oauth2/tokens/revoke",
			headers={
				"Authorization": f"Basic {_xero_basic_auth(client_id, client_secret)}",
				"Content-Type": "application/x-www-form-urlencoded",
				"Accept": "application/json",
			},
			data={"token": token},
			timeout=20,
		)
	except Exception as exc:
		return {"ok": False, "message": f"QuickBooks revoke failed: {exc}"}
	if not resp.ok:
		return {"ok": False, "message": f"QuickBooks revoke failed ({resp.status_code}): {_as_str(resp.text)}"}
	return {"ok": True, "message": "QuickBooks token revoked."}


@frappe.whitelist(methods=["POST", "GET"])
def quickbooks_disconnect(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	row = _integration_record("QuickBooks")
	row, _ = _quickbooks_apply_site_config_credentials(row)
	is_firelink_site = _is_firelink_local_site()
	force_revoke = _as_bool(kwargs.get("force_revoke") or kwargs.get("forceRevoke"))
	skip_remote_revoke = _as_bool(kwargs.get("skip_remote_revoke") or kwargs.get("skipRemoteRevoke"))
	# Default behavior is full disconnect (remote revoke included), including on FireLink.
	# Pass skip_remote_revoke=1 only when local clear is intended without Intuit-side revoke.
	should_revoke_remote = (not skip_remote_revoke) and ((not is_firelink_site) or force_revoke or is_firelink_site)
	revoke_result = _quickbooks_remote_disconnect(row) if should_revoke_remote else {
		"ok": True,
		"message": "Skipped remote revoke by request.",
	}
	row["quickbooksAccessToken"] = ""
	row["quickbooksRefreshToken"] = ""
	row["quickbooksTokenExpiresAt"] = ""
	row["quickbooksConnectedAt"] = ""
	row["quickbooksState"] = ""
	row["quickbooksRealmId"] = ""
	row["tenantId"] = ""
	row["enabled"] = False
	_persist_integration_record("QuickBooks", row)
	msg = "QuickBooks disconnected."
	ok = True
	if isinstance(revoke_result, dict):
		ok = _as_bool(revoke_result.get("ok")) if "ok" in revoke_result else True
		remote_msg = _as_str(revoke_result.get("message"))
		if remote_msg:
			msg = f"{msg} {remote_msg}"
	return {"ok": ok, "message": msg.strip()}


@frappe.whitelist()
def xero_list_connections(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	_ensure_customer_xero_fields()
	_ensure_supplier_xero_fields()
	_ensure_sales_invoice_xero_fields()
	row = _integration_record("Xero")
	row = _xero_apply_site_config_credentials(row)[0]
	row = _xero_refresh_if_needed(row)
	connections = _xero_fetch_connections(row)
	row["xeroConnectionsJson"] = json.dumps(connections)
	if connections:
		first = connections[0] if isinstance(connections[0], dict) else {}
		row["tenantId"] = _as_str(first.get("tenantId"))
		row["enabled"] = True
	_persist_integration_record("Xero", row)
	return {"ok": True, "connections": connections, "tenantId": _as_str(row.get("tenantId"))}


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
	if provider == "Xero":
		_ensure_customer_xero_fields()
		_ensure_supplier_xero_fields()
		_ensure_sales_invoice_xero_fields()

	if provider == "Xero":
		row = _integration_record("Xero")
		row = _xero_apply_site_config_credentials(row)[0]
		row = _xero_refresh_if_needed(row)
		try:
			connections = _xero_fetch_connections(row)
			row["xeroConnectionsJson"] = json.dumps(connections)
			if connections:
				first = connections[0] if isinstance(connections[0], dict) else {}
				row["tenantId"] = _as_str(first.get("tenantId"))
				row["enabled"] = True
			_persist_integration_record("Xero", row)
			return f"Xero connected. {len(connections)} organization connection(s) visible."
		except Exception:
			pass

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


def _provider_access_token(provider: str, row: dict[str, Any]) -> str:
	if provider == "QuickBooks":
		return _as_str(row.get("quickbooksAccessToken") or row.get("accessToken"))
	if provider == "MYOB":
		return _as_str(row.get("myobAccessToken") or row.get("accessToken") or row.get("xeroAccessToken"))
	return _as_str(row.get("accessToken") or row.get("xeroAccessToken") or row.get("quickbooksAccessToken"))


def _quickbooks_refresh_if_needed(row: dict[str, Any]) -> dict[str, Any]:
	if requests is None:
		return row
	row, _ = _quickbooks_apply_site_config_credentials(row)
	expires_raw = _as_str(row.get("quickbooksTokenExpiresAt"))
	access_token = _as_str(row.get("quickbooksAccessToken"))
	refresh_token = _as_str(row.get("quickbooksRefreshToken"))
	if access_token and expires_raw:
		try:
			expires = datetime.fromisoformat(expires_raw.replace("Z", "+00:00"))
			if expires.tzinfo is None:
				expires = expires.replace(tzinfo=timezone.utc)
			if expires > datetime.now(timezone.utc) + timedelta(minutes=2):
				return row
		except Exception:
			pass
	if not refresh_token:
		return row
	client_id = _as_str(row.get("clientId"))
	client_secret = _as_str(row.get("clientSecret"))
	token_url = _as_str(row.get("tokenUrl")) or _as_str(PROVIDER_DEFAULTS["QuickBooks"].get("tokenUrl"))
	if not client_id or not client_secret or not token_url:
		return row
	basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
	headers = {"Authorization": f"Basic {basic}", "Accept": "application/json"}
	resp = requests.post(token_url, headers=headers, data={"grant_type": "refresh_token", "refresh_token": refresh_token}, timeout=25)
	if int(resp.status_code) >= 300:
		return row
	data = resp.json() if hasattr(resp, "json") else {}
	new_access = _as_str(data.get("access_token"))
	new_refresh = _as_str(data.get("refresh_token"))
	expires_in = int(_as_int(data.get("expires_in"), 0) or 0)
	if new_access:
		row["quickbooksAccessToken"] = new_access
	if new_refresh:
		row["quickbooksRefreshToken"] = new_refresh
	if expires_in > 0:
		row["quickbooksTokenExpiresAt"] = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()
	_persist_integration_record("QuickBooks", row)
	return row


def _quickbooks_query_entity(row: dict[str, Any], entity: str, limit: int = 200) -> list[dict[str, Any]]:
	if requests is None:
		frappe.throw("QuickBooks sync unavailable (requests library missing).", frappe.ValidationError)
	row = _quickbooks_refresh_if_needed(row)
	token = _as_str(row.get("quickbooksAccessToken"))
	realm_id = _as_str(row.get("quickbooksRealmId") or row.get("tenantId"))
	if not token or not realm_id:
		frappe.throw("QuickBooks is not connected. Run Connect QuickBooks first.", frappe.ValidationError)

	configured_base = _as_str(row.get("baseUrl")) or _as_str(PROVIDER_DEFAULTS["QuickBooks"].get("baseUrl"))
	configured_base = configured_base.rstrip("/")
	prod_base = "https://quickbooks.api.intuit.com"
	sandbox_base = "https://sandbox-quickbooks.api.intuit.com"
	base_candidates = [configured_base] if configured_base else [prod_base]
	if configured_base == prod_base:
		base_candidates.append(sandbox_base)
	elif configured_base == sandbox_base:
		base_candidates.append(prod_base)
	elif sandbox_base not in base_candidates:
		base_candidates.append(sandbox_base)

	query = f"SELECT * FROM {entity} MAXRESULTS {max(1, min(int(limit), 1000))}"
	headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
	last_status = 0
	last_detail = ""
	for base in base_candidates:
		url = f"{base}/v3/company/{realm_id}/query"
		resp = requests.get(url, headers=headers, params={"query": query, "minorversion": "75"}, timeout=30)
		status = int(resp.status_code)
		if status < 300:
			if base != configured_base:
				row["baseUrl"] = base
				_persist_integration_record("QuickBooks", row)
			data = resp.json() if hasattr(resp, "json") else {}
			qr = data.get("QueryResponse") if isinstance(data, dict) else {}
			rows = qr.get(entity) if isinstance(qr, dict) and isinstance(qr.get(entity), list) else []
			return rows
		last_status = status
		last_detail = _as_str(getattr(resp, "text", ""))
		lower_detail = last_detail.lower()
		if not (status == 403 and ("applicationauthorizationfailed" in lower_detail or "errorcode=003100" in lower_detail or '"code":"3100"' in lower_detail)):
			break

	hint = ""
	if last_status == 403 and ("applicationauthorizationfailed" in last_detail.lower() or "errorcode=003100" in last_detail.lower() or '"code":"3100"' in last_detail.lower()):
		hint = " Ensure the connected company and app environment match (Production vs Sandbox), then reconnect QuickBooks."
	frappe.throw(f"QuickBooks query failed ({last_status}): {last_detail}{hint}", frappe.ValidationError)


def _quickbooks_find_customer_by_display_name(row: dict[str, Any], display_name: str) -> dict[str, Any] | None:
	if requests is None:
		frappe.throw("QuickBooks sync unavailable (requests library missing).", frappe.ValidationError)
	name = _as_str(display_name)
	if not name:
		return None
	row = _quickbooks_refresh_if_needed(row)
	token = _as_str(row.get("quickbooksAccessToken"))
	realm_id = _as_str(row.get("quickbooksRealmId") or row.get("tenantId"))
	if not token or not realm_id:
		frappe.throw("QuickBooks is not connected. Run Connect QuickBooks first.", frappe.ValidationError)

	configured_base = _as_str(row.get("baseUrl")) or _as_str(PROVIDER_DEFAULTS["QuickBooks"].get("baseUrl"))
	configured_base = configured_base.rstrip("/")
	prod_base = "https://quickbooks.api.intuit.com"
	sandbox_base = "https://sandbox-quickbooks.api.intuit.com"
	base_candidates = [configured_base] if configured_base else [prod_base]
	if configured_base == prod_base:
		base_candidates.append(sandbox_base)
	elif configured_base == sandbox_base:
		base_candidates.append(prod_base)
	elif sandbox_base not in base_candidates:
		base_candidates.append(sandbox_base)

	name_q = name.replace("\\", "\\\\").replace("'", "\\'")
	query = f"SELECT * FROM Customer WHERE DisplayName = '{name_q}' MAXRESULTS 1"
	headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
	for base in base_candidates:
		url = f"{base}/v3/company/{realm_id}/query"
		resp = requests.get(url, headers=headers, params={"query": query, "minorversion": "75"}, timeout=30)
		if int(resp.status_code) < 300:
			if base != configured_base:
				row["baseUrl"] = base
				_persist_integration_record("QuickBooks", row)
			data = resp.json() if hasattr(resp, "json") else {}
			qr = data.get("QueryResponse") if isinstance(data, dict) else {}
			rows = qr.get("Customer") if isinstance(qr, dict) and isinstance(qr.get("Customer"), list) else []
			return rows[0] if rows else None
	return None


def _quickbooks_push_customer(row: dict[str, Any], reference_name: str, document: dict[str, Any]) -> dict[str, Any]:
	if requests is None:
		frappe.throw("QuickBooks sync unavailable (requests library missing).", frappe.ValidationError)
	row = _quickbooks_refresh_if_needed(row)
	token = _as_str(row.get("quickbooksAccessToken"))
	realm_id = _as_str(row.get("quickbooksRealmId") or row.get("tenantId"))
	if not token or not realm_id:
		frappe.throw("QuickBooks is not connected. Run Connect QuickBooks first.", frappe.ValidationError)

	display_name = (
		_as_str(document.get("customer_name"))
		or _as_str(document.get("customer_name1"))
		or _as_str(document.get("customer"))
		or _as_str(reference_name)
	)
	if not display_name:
		frappe.throw("Customer name is required for QuickBooks push.", frappe.ValidationError)

	email = _as_str(document.get("email_id"))
	phone = _as_str(document.get("mobile_no") or document.get("phone"))

	configured_base = _as_str(row.get("baseUrl")) or _as_str(PROVIDER_DEFAULTS["QuickBooks"].get("baseUrl"))
	configured_base = configured_base.rstrip("/")
	prod_base = "https://quickbooks.api.intuit.com"
	sandbox_base = "https://sandbox-quickbooks.api.intuit.com"
	base_candidates = [configured_base] if configured_base else [prod_base]
	if configured_base == prod_base:
		base_candidates.append(sandbox_base)
	elif configured_base == sandbox_base:
		base_candidates.append(prod_base)
	elif sandbox_base not in base_candidates:
		base_candidates.append(sandbox_base)

	existing = _quickbooks_find_customer_by_display_name(row, display_name)
	base_payload: dict[str, Any] = {"DisplayName": display_name}
	if email:
		base_payload["PrimaryEmailAddr"] = {"Address": email}
	if phone:
		base_payload["PrimaryPhone"] = {"FreeFormNumber": phone}

	headers = {
		"Authorization": f"Bearer {token}",
		"Accept": "application/json",
		"Content-Type": "application/json",
	}
	last_status = 0
	last_detail = ""
	for base in base_candidates:
		url = f"{base}/v3/company/{realm_id}/customer"
		payload = dict(base_payload)
		if isinstance(existing, dict):
			payload["Id"] = _as_str(existing.get("Id"))
			payload["SyncToken"] = _as_str(existing.get("SyncToken"))
			payload["sparse"] = True
			url = f"{url}?operation=update"
		resp = requests.post(url, headers=headers, json=payload, params={"minorversion": "75"}, timeout=30)
		status = int(resp.status_code)
		if status < 300:
			if base != configured_base:
				row["baseUrl"] = base
				_persist_integration_record("QuickBooks", row)
			data = resp.json() if hasattr(resp, "json") else {}
			customer = data.get("Customer") if isinstance(data, dict) and isinstance(data.get("Customer"), dict) else {}
			return customer
		last_status = status
		last_detail = _as_str(getattr(resp, "text", ""))
		if status == 400 and "Duplicate Name Exists Error" in last_detail and not existing:
			existing = _quickbooks_find_customer_by_display_name(row, display_name)
			continue
		lower_detail = last_detail.lower()
		if not (status == 403 and ("applicationauthorizationfailed" in lower_detail or "errorcode=003100" in lower_detail or '"code":"3100"' in lower_detail)):
			break

	hint = ""
	if last_status == 403 and ("applicationauthorizationfailed" in last_detail.lower() or "errorcode=003100" in last_detail.lower() or '"code":"3100"' in last_detail.lower()):
		hint = " Ensure the connected company and app environment match (Production vs Sandbox), then reconnect QuickBooks."
	frappe.throw(f"QuickBooks customer push failed ({last_status}): {last_detail}{hint}", frappe.ValidationError)

def _quickbooks_email(value: dict[str, Any]) -> str:
	if not isinstance(value, dict):
		return ""
	primary = value.get("PrimaryEmailAddr")
	if isinstance(primary, dict):
		return _as_str(primary.get("Address"))
	return ""


def _quickbooks_phone(value: dict[str, Any]) -> str:
	if not isinstance(value, dict):
		return ""
	for key in ("PrimaryPhone", "Mobile", "AlternatePhone"):
		part = value.get(key)
		if isinstance(part, dict):
			num = _as_str(part.get("FreeFormNumber"))
			if num:
				return num
	return ""


def _quickbooks_customer_to_xero_contact(row: dict[str, Any]) -> dict[str, Any]:
	name = _as_str(row.get("DisplayName") or row.get("CompanyName") or row.get("FullyQualifiedName") or row.get("GivenName") or row.get("Id"))
	if not name:
		name = "QuickBooks Customer"
	out = {
		"ContactID": _as_str(row.get("Id")),
		"Name": name,
		"ContactNumber": _as_str(row.get("Id")),
		"IsCustomer": True,
	}
	email = _quickbooks_email(row)
	if email:
		out["EmailAddress"] = email
	phone = _quickbooks_phone(row)
	if phone:
		out["Phones"] = [{"PhoneType": "MOBILE", "PhoneNumber": phone}]
	return out


def _quickbooks_vendor_to_xero_contact(row: dict[str, Any]) -> dict[str, Any]:
	name = _as_str(row.get("DisplayName") or row.get("CompanyName") or row.get("PrintOnCheckName") or row.get("GivenName") or row.get("Id"))
	if not name:
		name = "QuickBooks Supplier"
	out = {
		"ContactID": _as_str(row.get("Id")),
		"Name": name,
		"ContactNumber": _as_str(row.get("Id")),
		"IsSupplier": True,
	}
	email = _quickbooks_email(row)
	if email:
		out["EmailAddress"] = email
	phone = _quickbooks_phone(row)
	if phone:
		out["Phones"] = [{"PhoneType": "MOBILE", "PhoneNumber": phone}]
	return out


def _quickbooks_item_to_xero_item(row: dict[str, Any]) -> dict[str, Any]:
	sales = row.get("SalesPrice")
	if sales is None and isinstance(row.get("UnitPrice"), (int, float, str)):
		sales = row.get("UnitPrice")
	name = _as_str(row.get("Name") or row.get("FullyQualifiedName") or row.get("Id"))
	code = _as_str(row.get("Sku") or row.get("Name") or row.get("Id"))
	return {
		"ItemID": _as_str(row.get("Id")),
		"Code": code,
		"Name": name,
		"Description": _as_str(row.get("Description")),
		"SalesDetails": {"UnitPrice": float(_as_float(sales, 0.0))},
	}


def _quickbooks_invoice_to_xero_invoice(row: dict[str, Any]) -> dict[str, Any]:
	cust_ref = row.get("CustomerRef") if isinstance(row.get("CustomerRef"), dict) else {}
	contact_id = _as_str(cust_ref.get("value"))
	line_items = []
	for ln in (row.get("Line") or []):
		if not isinstance(ln, dict):
			continue
		detail_type = _as_str(ln.get("DetailType"))
		if detail_type != "SalesItemLineDetail":
			continue
		d = ln.get("SalesItemLineDetail") if isinstance(ln.get("SalesItemLineDetail"), dict) else {}
		qty = float(_as_float(d.get("Qty"), 1.0) or 1.0)
		unit = float(_as_float(d.get("UnitPrice"), 0.0))
		amount = float(_as_float(ln.get("Amount"), unit * qty))
		item_ref = d.get("ItemRef") if isinstance(d.get("ItemRef"), dict) else {}
		line_items.append({
			"LineItemID": _as_str(ln.get("Id")),
			"Description": _as_str(ln.get("Description") or item_ref.get("name") or "QuickBooks line"),
			"Quantity": qty,
			"UnitAmount": unit,
			"LineAmount": amount,
			"ItemID": _as_str(item_ref.get("value")),
			"ItemCode": _as_str(item_ref.get("name")),
		})
	date_val = _as_str(row.get("TxnDate") or frappe.utils.nowdate())
	due_val = _as_str(row.get("DueDate") or date_val)
	return {
		"InvoiceID": _as_str(row.get("Id")),
		"InvoiceNumber": _as_str(row.get("DocNumber") or row.get("Id")),
		"Date": date_val,
		"DateString": date_val,
		"DueDate": due_val,
		"DueDateString": due_val,
		"Total": float(_as_float(row.get("TotalAmt"), 0.0)),
		"Contact": {"ContactID": contact_id},
		"LineItems": line_items,
	}


def _quickbooks_upsert_customer_rows(rows: list[dict[str, Any]]) -> tuple[int, int, list[str]]:
	created = 0
	updated = 0
	errors: list[str] = []
	for raw in rows:
		try:
			contact = _quickbooks_customer_to_xero_contact(raw if isinstance(raw, dict) else {})
			cid = _as_str(contact.get("ContactID"))
			existed = bool(cid and frappe.db.exists("Customer", {"xero_contact_id": cid}))
			name = _upsert_customer_from_xero_contact(contact)
			if not name:
				continue
			if existed:
				updated += 1
			else:
				created += 1
		except Exception as exc:
			errors.append(_as_str(exc))
	return created, updated, errors[:20]


def _quickbooks_upsert_supplier_rows(rows: list[dict[str, Any]]) -> tuple[int, int, list[str]]:
	created = 0
	updated = 0
	errors: list[str] = []
	for raw in rows:
		try:
			contact = _quickbooks_vendor_to_xero_contact(raw if isinstance(raw, dict) else {})
			cid = _as_str(contact.get("ContactID"))
			existed = bool(cid and frappe.db.exists("Supplier", {"xero_contact_id": cid}))
			name = _upsert_supplier_from_xero_contact(contact)
			if not name:
				continue
			if existed:
				updated += 1
			else:
				created += 1
		except Exception as exc:
			errors.append(_as_str(exc))
	return created, updated, errors[:20]


def _quickbooks_upsert_item_rows(rows: list[dict[str, Any]]) -> tuple[int, int, list[str]]:
	created = 0
	updated = 0
	errors: list[str] = []
	for raw in rows:
		try:
			item = _quickbooks_item_to_xero_item(raw if isinstance(raw, dict) else {})
			iid = _as_str(item.get("ItemID"))
			existed = bool(iid and frappe.db.exists("Item", {"xero_item_id": iid}))
			name = _upsert_item_from_xero_item(item)
			if not name:
				continue
			if existed:
				updated += 1
			else:
				created += 1
		except Exception as exc:
			errors.append(_as_str(exc))
	return created, updated, errors[:20]


def _quickbooks_upsert_invoice_rows(rows: list[dict[str, Any]]) -> tuple[int, int, list[str]]:
	created = 0
	updated = 0
	errors: list[str] = []
	for raw in rows:
		try:
			inv = _quickbooks_invoice_to_xero_invoice(raw if isinstance(raw, dict) else {})
			iid = _as_str(inv.get("InvoiceID"))
			existed = bool(iid and frappe.db.exists("Sales Invoice", {"xero_invoice_id": iid}))
			name = _upsert_sales_invoice_from_xero_invoice(inv)
			if not name:
				continue
			if existed:
				updated += 1
			else:
				created += 1
		except Exception as exc:
			errors.append(_as_str(exc))
	return created, updated, errors[:20]

def _myob_company_uri(row: dict[str, Any]) -> str:
	# MYOB can store company-file URI directly in tenantId.
	tenant = _as_str(row.get("tenantId"))
	base = _as_str(row.get("baseUrl")) or _as_str(PROVIDER_DEFAULTS["MYOB"].get("baseUrl"))
	if tenant.lower().startswith("http"):
		return tenant.rstrip("/")
	if tenant:
		return f"{base.rstrip('/')}/{tenant.strip('/')}"
	return base.rstrip("/")


def _myob_list_entity(row: dict[str, Any], endpoint: str) -> list[dict[str, Any]]:
	if requests is None:
		frappe.throw("MYOB sync unavailable (requests library missing).", frappe.ValidationError)
	access_token = _provider_access_token("MYOB", row)
	client_id = _as_str(row.get("clientId"))
	cf_uri = _myob_company_uri(row)
	if not access_token or not client_id or not cf_uri or cf_uri.endswith("/accountright"):
		frappe.throw("MYOB is not connected/configured. Ensure access token, client ID, and company file URI are set.", frappe.ValidationError)
	url = f"{cf_uri.rstrip('/')}/{endpoint.lstrip('/')}"
	headers = {
		"Authorization": f"Bearer {access_token}",
		"x-myobapi-key": client_id,
		"x-myobapi-version": "v2",
		"Accept": "application/json",
	}
	resp = requests.get(url, headers=headers, timeout=30)
	if int(resp.status_code) >= 300:
		detail = _as_str(getattr(resp, "text", ""))
		frappe.throw(f"MYOB query failed ({resp.status_code}): {detail}", frappe.ValidationError)
	data = resp.json() if hasattr(resp, "json") else {}
	if isinstance(data, dict) and isinstance(data.get("Items"), list):
		return data.get("Items")
	if isinstance(data, list):
		return data
	return []


def _provider_manual_sync_snapshot(provider: str, entity: str, row: dict[str, Any]) -> dict[str, Any]:
	provider = _normalize_provider_name(provider, "Xero")
	if provider == "QuickBooks":
		entity_map = {
			"customer": "Customer",
			"supplier": "Vendor",
			"invoice": "Invoice",
			"payment": "Payment",
			"item": "Item",
		}
		qb_entity = entity_map.get(entity)
		if not qb_entity:
			frappe.throw(f"QuickBooks sync entity not supported: {entity}", frappe.ValidationError)
		rows = _quickbooks_query_entity(row, qb_entity)
		return {"ok": True, "provider": provider, "entity": entity, "count": len(rows), "message": f"QuickBooks {entity} sync snapshot complete ({len(rows)} rows)."}
	if provider == "MYOB":
		endpoint_map = {
			"customer": "Contact/Customer?$top=400",
			"supplier": "Contact/Supplier?$top=400",
			"invoice": "Sale/Invoice?$top=400",
			"payment": "Sale/CustomerPayment?$top=400",
			"item": "Inventory/Item?$top=400",
		}
		ep = endpoint_map.get(entity)
		if not ep:
			frappe.throw(f"MYOB sync entity not supported: {entity}", frappe.ValidationError)
		rows = _myob_list_entity(row, ep)
		return {"ok": True, "provider": provider, "entity": entity, "count": len(rows), "message": f"MYOB {entity} sync snapshot complete ({len(rows)} rows)."}
	# Custom is hidden from tenant UI; keep explicit safety guard.
	frappe.throw(f"{provider} manual sync is not enabled in this build.", frappe.ValidationError)



@frappe.whitelist(methods=["POST"])
def sync_entity(**kwargs):
	entity = _as_str(kwargs.get("entity")).lower()
	operation = _as_str(kwargs.get("operation")).lower() or "update"
	reference_name = _as_str(kwargs.get("reference_name") or kwargs.get("referenceName"))
	provider = _normalize_provider_name(kwargs.get("provider") or kwargs.get("integration_provider"), "Xero")
	document = kwargs.get("document") if isinstance(kwargs.get("document"), dict) else {}
	is_manual_pull = reference_name.startswith("__manual_")
	is_push = operation in {"create", "update", "delete"} and bool(document) and not is_manual_pull
	_ensure_accounting_sync_meta_fields()
	if is_push:
		if provider == "QuickBooks":
			row = _integration_record(provider)
			row = _quickbooks_refresh_if_needed(row)
			_persist_integration_record(provider, row)
			if entity == "customer":
				if operation == "delete":
					return {"ok": True, "message": f"Customer delete push not enabled for {provider} (safe mode)."}
				try:
					out = _quickbooks_push_customer(row, reference_name, document)
					qb_customer_id = _as_str(out.get("Id"))
					if reference_name and frappe.db.exists("Customer", reference_name):
						_set_accounting_sync_meta("Customer", reference_name, provider, "Synced", qb_customer_id, "")
						frappe.db.commit()
				except Exception as exc:
					if reference_name and frappe.db.exists("Customer", reference_name):
						_set_accounting_sync_meta("Customer", reference_name, provider, "Error", "", _as_str(exc))
						frappe.db.commit()
					raise
				_persist_integration_record(provider, row)
				return {"ok": True, "message": f"Customer pushed to {provider} ({qb_customer_id or 'ok'})."}
			frappe.throw(f"{provider} push is not enabled for {entity} in this build.", frappe.ValidationError)

		row = _integration_record(provider)
		row = _xero_apply_site_config_credentials(row)[0]
		row = _xero_refresh_and_reselect_tenant(_xero_refresh_if_needed(row))
		_persist_integration_record(provider, row)
		if entity == "customer":
			if operation == "delete":
				return {"ok": True, "message": f"Customer delete push not enabled for {provider} (safe mode)."}
			try:
				out = _xero_push_contact(row, reference_name, "Customer", document)
				contact_id = _as_str(out.get("ContactID"))
				contact_number = _as_str(out.get("ContactNumber"))
				if contact_id and reference_name and frappe.db.exists("Customer", reference_name):
					frappe.db.set_value("Customer", reference_name, {
						"xero_contact_id": contact_id,
						"xero_contact_number": contact_number,
						"xero_last_synced_at": frappe.utils.now_datetime(),
					}, update_modified=False)
					_set_accounting_sync_meta("Customer", reference_name, provider, "Synced", contact_id, "")
					frappe.db.commit()
			except Exception as exc:
				if reference_name and frappe.db.exists("Customer", reference_name):
					_set_accounting_sync_meta("Customer", reference_name, provider, "Error", "", _as_str(exc))
					frappe.db.commit()
				raise
			_persist_integration_record(provider, row)
			return {"ok": True, "message": f"Customer pushed to {provider} ({contact_id or 'ok'})."}
		if entity == "supplier":
			if operation == "delete":
				return {"ok": True, "message": f"Supplier delete push not enabled for {provider} (safe mode)."}
			try:
				out = _xero_push_contact(row, reference_name, "Supplier", document)
				contact_id = _as_str(out.get("ContactID"))
				contact_number = _as_str(out.get("ContactNumber"))
				if contact_id and reference_name and frappe.db.exists("Supplier", reference_name):
					frappe.db.set_value("Supplier", reference_name, {
						"xero_contact_id": contact_id,
						"xero_contact_number": contact_number,
						"xero_last_synced_at": frappe.utils.now_datetime(),
					}, update_modified=False)
					_set_accounting_sync_meta("Supplier", reference_name, provider, "Synced", contact_id, "")
					frappe.db.commit()
			except Exception as exc:
				if reference_name and frappe.db.exists("Supplier", reference_name):
					_set_accounting_sync_meta("Supplier", reference_name, provider, "Error", "", _as_str(exc))
					frappe.db.commit()
				raise
			_persist_integration_record(provider, row)
			return {"ok": True, "message": f"Supplier pushed to {provider} ({contact_id or 'ok'})."}
		if entity == "invoice":
			if operation == "delete":
				return {"ok": True, "message": f"Invoice delete push not enabled for {provider} (safe mode)."}
			try:
				out = _xero_push_invoice(row, reference_name, document)
				invoice_id = _as_str(out.get("InvoiceID"))
				invoice_number = _as_str(out.get("InvoiceNumber"))
				if invoice_id and reference_name and frappe.db.exists("Sales Invoice", reference_name):
					frappe.db.set_value("Sales Invoice", reference_name, {
						"xero_invoice_id": invoice_id,
						"xero_invoice_number": invoice_number,
						"xero_last_synced_at": frappe.utils.now_datetime(),
					}, update_modified=False)
					_set_accounting_sync_meta("Sales Invoice", reference_name, provider, "Synced", invoice_id, "")
					frappe.db.commit()
			except Exception as exc:
				if reference_name and frappe.db.exists("Sales Invoice", reference_name):
					_set_accounting_sync_meta("Sales Invoice", reference_name, provider, "Error", "", _as_str(exc))
					frappe.db.commit()
				raise
			_persist_integration_record(provider, row)
			return {"ok": True, "message": f"Invoice pushed to {provider} ({invoice_number or invoice_id or 'ok'})."}
		if entity == "payment":
			if operation == "delete":
				return {"ok": True, "message": f"Payment delete push not enabled for {provider} (safe mode)."}
			try:
				out = _xero_push_payment(row, reference_name, document)
				payment_id = _as_str(out.get("PaymentID"))
				payment_ref = _as_str(out.get("Reference"))
				if payment_id and reference_name and frappe.db.exists("Payment Entry", reference_name):
					frappe.db.set_value("Payment Entry", reference_name, {
						"xero_payment_id": payment_id,
						"xero_payment_ref": payment_ref,
						"xero_last_synced_at": frappe.utils.now_datetime(),
					}, update_modified=False)
					_set_accounting_sync_meta("Payment Entry", reference_name, provider, "Synced", payment_id, "")
					frappe.db.commit()
			except Exception as exc:
				if reference_name and frappe.db.exists("Payment Entry", reference_name):
					_set_accounting_sync_meta("Payment Entry", reference_name, provider, "Error", "", _as_str(exc))
					frappe.db.commit()
				raise
			_persist_integration_record(provider, row)
			return {"ok": True, "message": f"Payment pushed to {provider} ({payment_id or 'ok'})."}

	if entity == "customer":
		return sync_customer(**kwargs)
	if entity == "supplier":
		return sync_supplier(**kwargs)
	if entity == "invoice":
		return sync_invoice(**kwargs)
	if entity == "item":
		return sync_item(**kwargs)
	if entity == "payment":
		return sync_payment(**kwargs)
	frappe.throw(f"Sync for entity '{entity or 'unknown'}' is not implemented yet.", frappe.ValidationError)


@frappe.whitelist(methods=["POST"])
def sync_customer(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)

	provider = _normalize_provider_name(kwargs.get("provider") or kwargs.get("integration_provider"), "Xero")
	if provider == "QuickBooks":
		row = _integration_record(provider)
		rows = _quickbooks_query_entity(row, "Customer")
		created, updated, errors = _quickbooks_upsert_customer_rows(rows)
		frappe.db.commit()
		return {"ok": True, "provider": provider, "entity": "customer", "count": len(rows), "created": created, "updated": updated, "errors": errors, "message": f"{provider} customer sync complete. {created} created, {updated} updated, {len(errors)} failed."}
	if provider == "MYOB":
		row = _integration_record(provider)
		return _provider_manual_sync_snapshot(provider, "customer", row)

	_ensure_customer_xero_fields()
	row = _integration_record(provider)
	row = _xero_apply_site_config_credentials(row)[0]
	row = _xero_refresh_if_needed(row)
	connections = _xero_fetch_connections(row)
	row["xeroConnectionsJson"] = json.dumps(connections)
	if connections and not _as_str(row.get("tenantId")):
		first = connections[0] if isinstance(connections[0], dict) else {}
		row["tenantId"] = _as_str(first.get("tenantId"))

	contacts = _xero_fetch_contacts(row)
	created = 0
	updated = 0
	errors: list[str] = []

	for contact in contacts:
		try:
			if not isinstance(contact, dict):
				continue
			if not _xero_contact_matches_entity(contact, "customer"):
				continue
			contact_id = _as_str(contact.get("ContactID"))
			existed = bool(contact_id and frappe.db.exists("Customer", {"xero_contact_id": contact_id}))
			name = _upsert_customer_from_xero_contact(contact)
			if not name:
				continue
			if existed:
				updated += 1
			else:
				created += 1
		except Exception as exc:
			errors.append(_as_str(exc))

	_persist_integration_record(provider, row)
	frappe.db.commit()
	return {
		"ok": True,
		"provider": provider,
		"entity": "customer",
		"count": len(contacts),
		"created": created,
		"updated": updated,
		"errors": errors[:20],
		"message": f"{provider} customer sync complete. {created} created, {updated} updated, {len(errors)} failed.",
	}


@frappe.whitelist(methods=["POST"])
def sync_supplier(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	provider = _normalize_provider_name(kwargs.get("provider") or kwargs.get("integration_provider"), "Xero")
	if provider == "QuickBooks":
		row = _integration_record(provider)
		rows = _quickbooks_query_entity(row, "Vendor")
		created, updated, errors = _quickbooks_upsert_supplier_rows(rows)
		frappe.db.commit()
		return {"ok": True, "provider": provider, "entity": "supplier", "count": len(rows), "created": created, "updated": updated, "errors": errors, "message": f"{provider} supplier sync complete. {created} created, {updated} updated, {len(errors)} failed."}
	if provider == "MYOB":
		row = _integration_record(provider)
		return _provider_manual_sync_snapshot(provider, "supplier", row)

	_ensure_supplier_xero_fields()
	row = _integration_record(provider)
	row = _xero_apply_site_config_credentials(row)[0]
	row = _xero_refresh_if_needed(row)
	connections = _xero_fetch_connections(row)
	row["xeroConnectionsJson"] = json.dumps(connections)
	if connections and not _as_str(row.get("tenantId")):
		first = connections[0] if isinstance(connections[0], dict) else {}
		row["tenantId"] = _as_str(first.get("tenantId"))

	contacts = _xero_fetch_contacts(row)
	created = 0
	updated = 0
	errors: list[str] = []
	for contact in contacts:
		try:
			if not isinstance(contact, dict):
				continue
			if not _xero_contact_matches_entity(contact, "supplier"):
				continue
			contact_id = _as_str(contact.get("ContactID"))
			existed = bool(contact_id and frappe.db.exists("Supplier", {"xero_contact_id": contact_id}))
			name = _upsert_supplier_from_xero_contact(contact)
			if not name:
				continue
			if existed:
				updated += 1
			else:
				created += 1
		except Exception as exc:
			errors.append(_as_str(exc))

	_persist_integration_record(provider, row)
	frappe.db.commit()
	return {
		"ok": True,
		"provider": provider,
		"entity": "supplier",
		"count": len(contacts),
		"created": created,
		"updated": updated,
		"errors": errors[:20],
		"message": f"{provider} supplier sync complete. {created} created, {updated} updated, {len(errors)} failed.",
	}


@frappe.whitelist(methods=["POST"])
def sync_invoice(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	provider = _normalize_provider_name(kwargs.get("provider") or kwargs.get("integration_provider"), "Xero")
	if provider == "QuickBooks":
		row = _integration_record(provider)
		rows = _quickbooks_query_entity(row, "Invoice")
		created, updated, errors = _quickbooks_upsert_invoice_rows(rows)
		frappe.db.commit()
		return {"ok": True, "provider": provider, "entity": "invoice", "count": len(rows), "created": created, "updated": updated, "errors": errors, "message": f"{provider} invoice sync complete. {created} created, {updated} updated, {len(errors)} failed."}
	if provider == "MYOB":
		row = _integration_record(provider)
		return _provider_manual_sync_snapshot(provider, "invoice", row)

	_ensure_sales_invoice_xero_fields()
	_ensure_customer_xero_fields()
	_ensure_accounting_sync_meta_fields()
	row = _integration_record(provider)
	row = _xero_apply_site_config_credentials(row)[0]
	row = _xero_refresh_if_needed(row)
	connections = _xero_fetch_connections(row)
	row["xeroConnectionsJson"] = json.dumps(connections)
	if connections and not _as_str(row.get("tenantId")):
		first = connections[0] if isinstance(connections[0], dict) else {}
		row["tenantId"] = _as_str(first.get("tenantId"))

	invoices = _xero_fetch_invoices(row)
	created = 0
	updated = 0
	errors: list[str] = []
	for invoice in invoices:
		try:
			if not isinstance(invoice, dict):
				continue
			invoice_id = _as_str(invoice.get("InvoiceID"))
			existed = bool(invoice_id and frappe.db.exists("Sales Invoice", {"xero_invoice_id": invoice_id}))
			name = _upsert_sales_invoice_from_xero_invoice(invoice)
			if not name:
				continue
			if existed:
				updated += 1
			else:
				created += 1
		except Exception as exc:
			errors.append(_as_str(exc))

	_persist_integration_record(provider, row)
	frappe.db.commit()
	return {
		"ok": True,
		"provider": provider,
		"entity": "invoice",
		"count": len(invoices),
		"created": created,
		"updated": updated,
		"errors": errors[:20],
		"message": f"{provider} invoice sync complete. {created} created, {updated} updated, {len(errors)} failed.",
	}


@frappe.whitelist(methods=["POST"])
def sync_item(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	provider = _normalize_provider_name(kwargs.get("provider") or kwargs.get("integration_provider"), "Xero")
	if provider == "QuickBooks":
		row = _integration_record(provider)
		rows = _quickbooks_query_entity(row, "Item")
		created, updated, errors = _quickbooks_upsert_item_rows(rows)
		frappe.db.commit()
		return {"ok": True, "provider": provider, "entity": "item", "count": len(rows), "created": created, "updated": updated, "errors": errors, "message": f"{provider} item sync complete. {created} created, {updated} updated, {len(errors)} failed."}
	if provider == "MYOB":
		row = _integration_record(provider)
		return _provider_manual_sync_snapshot(provider, "item", row)

	_ensure_item_xero_fields()
	_ensure_accounting_sync_meta_fields()
	row = _integration_record(provider)
	row = _xero_apply_site_config_credentials(row)[0]
	row = _xero_refresh_if_needed(row)
	connections = _xero_fetch_connections(row)
	row["xeroConnectionsJson"] = json.dumps(connections)
	if connections and not _as_str(row.get("tenantId")):
		first = connections[0] if isinstance(connections[0], dict) else {}
		row["tenantId"] = _as_str(first.get("tenantId"))

	items = _xero_fetch_items(row)
	created = 0
	updated = 0
	errors: list[str] = []
	for item_row in items:
		try:
			if not isinstance(item_row, dict):
				continue
			xero_item_id = _as_str(item_row.get("ItemID"))
			existed = bool(xero_item_id and frappe.db.exists("Item", {"xero_item_id": xero_item_id}))
			name = _upsert_item_from_xero_item(item_row)
			if not name:
				continue
			if existed:
				updated += 1
			else:
				created += 1
		except Exception as exc:
			errors.append(_as_str(exc))

	_persist_integration_record(provider, row)
	frappe.db.commit()
	return {
		"ok": True,
		"provider": provider,
		"entity": "item",
		"count": len(items),
		"created": created,
		"updated": updated,
		"errors": errors[:20],
		"message": f"{provider} item sync complete. {created} created, {updated} updated, {len(errors)} failed.",
	}


@frappe.whitelist(methods=["POST"])
def sync_payment(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	provider = _normalize_provider_name(kwargs.get("provider") or kwargs.get("integration_provider"), "Xero")
	if provider in {"QuickBooks", "MYOB"}:
		row = _integration_record(provider)
		return _provider_manual_sync_snapshot(provider, "payment", row)

	_ensure_payment_entry_xero_fields()
	_ensure_sales_invoice_xero_fields()
	_ensure_accounting_sync_meta_fields()
	row = _integration_record(provider)
	row = _xero_apply_site_config_credentials(row)[0]
	row = _xero_refresh_if_needed(row)
	connections = _xero_fetch_connections(row)
	row["xeroConnectionsJson"] = json.dumps(connections)
	if connections and not _as_str(row.get("tenantId")):
		first = connections[0] if isinstance(connections[0], dict) else {}
		row["tenantId"] = _as_str(first.get("tenantId"))

	payments = _xero_fetch_payments(row)
	created = 0
	updated = 0
	errors: list[str] = []
	for payment in payments:
		try:
			if not isinstance(payment, dict):
				continue
			payment_id = _as_str(payment.get("PaymentID"))
			existed = bool(payment_id and frappe.db.exists("Payment Entry", {"xero_payment_id": payment_id}))
			name = _upsert_payment_entry_from_xero_payment(payment)
			if not name:
				continue
			if existed:
				updated += 1
			else:
				created += 1
		except Exception as exc:
			errors.append(_as_str(exc))

	_persist_integration_record(provider, row)
	frappe.db.commit()
	return {
		"ok": True,
		"provider": provider,
		"entity": "payment",
		"count": len(payments),
		"created": created,
		"updated": updated,
		"errors": errors[:20],
		"message": f"{provider} payment sync complete. {created} created, {updated} updated, {len(errors)} failed.",
	}


def _as_mapping_rows(raw: Any) -> list[dict[str, Any]]:
	if isinstance(raw, list):
		return [row for row in raw if isinstance(row, dict)]
	if isinstance(raw, str):
		try:
			parsed = json.loads(raw)
			if isinstance(parsed, list):
				return [row for row in parsed if isinstance(row, dict)]
		except Exception:
			return []
	return []


@frappe.whitelist(methods=["POST"])
def import_chart_of_accounts(**kwargs):
	provider = _normalize_provider_name(kwargs.get("provider") or kwargs.get("integration_provider"), "Xero")
	row = _integration_record(provider)
	out: list[dict[str, Any]] = []
	if provider == "QuickBooks":
		rows = _quickbooks_query_entity(row, "Account", 500)
		for acc in rows:
			if not isinstance(acc, dict):
				continue
			out.append({
				"id": _as_str(acc.get("Id")),
				"code": _as_str(acc.get("AcctNum") or acc.get("FullyQualifiedName")),
				"name": _as_str(acc.get("Name") or acc.get("FullyQualifiedName")),
				"type": _as_str(acc.get("AccountType") or acc.get("Classification")),
				"active": not _as_bool(acc.get("Active") is False),
			})
	elif provider == "MYOB":
		rows = _myob_list_entity(row, "GeneralLedger/Account?$top=500")
		for acc in rows:
			if not isinstance(acc, dict):
				continue
			out.append({
				"id": _as_str(acc.get("UID") or acc.get("Id")),
				"code": _as_str(acc.get("DisplayID") or acc.get("Number")),
				"name": _as_str(acc.get("Name")),
				"type": _as_str(acc.get("Type") or acc.get("Classification")),
				"active": not _as_bool(acc.get("IsInactive")),
			})
	else:
		row = _xero_apply_site_config_credentials(row)[0]
		row = _xero_refresh_if_needed(row)
		accounts = _xero_fetch_accounts(row)
		for acc in accounts:
			if not isinstance(acc, dict):
				continue
			out.append({
				"id": _as_str(acc.get("AccountID")),
				"code": _as_str(acc.get("Code")),
				"name": _as_str(acc.get("Name")),
				"type": _as_str(acc.get("Type")),
				"active": _as_str(acc.get("Status")).upper() != "ARCHIVED",
			})
	row["xeroChartAccountsJson"] = json.dumps(out)
	_persist_integration_record(provider, row)
	return {"ok": True, "provider": provider, "accounts": out, "count": len(out)}


@frappe.whitelist(methods=["GET", "POST"])
def list_chart_mappings(**kwargs):
	provider = _as_str(kwargs.get("provider") or kwargs.get("integration_provider") or "Xero")
	row = _integration_record(provider if provider in PROVIDERS else "Xero")
	mappings = _as_mapping_rows(row.get("chartMappingsJson"))
	return {"ok": True, "provider": provider, "mappings": mappings}


@frappe.whitelist(methods=["POST"])
def save_chart_mappings(**kwargs):
	provider = _as_str(kwargs.get("provider") or kwargs.get("integration_provider") or "Xero")
	row = _integration_record(provider if provider in PROVIDERS else "Xero")
	mappings = _as_mapping_rows(kwargs.get("mappings"))
	row["chartMappingsJson"] = json.dumps(mappings)
	_persist_integration_record(provider if provider in PROVIDERS else "Xero", row)
	return {"ok": True, "provider": provider, "saved": len(mappings)}


@frappe.whitelist(methods=["POST"])
def import_tax_codes(**kwargs):
	provider = _normalize_provider_name(kwargs.get("provider") or kwargs.get("integration_provider"), "Xero")
	row = _integration_record(provider)
	out: list[dict[str, Any]] = []
	if provider == "QuickBooks":
		rows = _quickbooks_query_entity(row, "TaxCode", 500)
		for rate in rows:
			if not isinstance(rate, dict):
				continue
			out.append({
				"id": _as_str(rate.get("Id")),
				"code": _as_str(rate.get("Name")),
				"name": _as_str(rate.get("Name") or rate.get("Description")),
				"rate": 0.0,
				"active": _as_bool(rate.get("Active", True)),
			})
	elif provider == "MYOB":
		rows = _myob_list_entity(row, "GeneralLedger/TaxCode?$top=500")
		for rate in rows:
			if not isinstance(rate, dict):
				continue
			out.append({
				"id": _as_str(rate.get("UID") or rate.get("Id")),
				"code": _as_str(rate.get("Code")),
				"name": _as_str(rate.get("Description") or rate.get("Code")),
				"rate": _as_float(rate.get("Rate"), 0.0),
				"active": not _as_bool(rate.get("IsInactive")),
			})
	else:
		row = _xero_apply_site_config_credentials(row)[0]
		row = _xero_refresh_if_needed(row)
		tax_rates = _xero_fetch_tax_rates(row)
		for rate in tax_rates:
			if not isinstance(rate, dict):
				continue
			out.append({
				"id": _as_str(rate.get("TaxType") or rate.get("TaxRateID")),
				"code": _as_str(rate.get("TaxType")),
				"name": _as_str(rate.get("Name")),
				"rate": _as_float(rate.get("EffectiveRate"), 0.0),
				"active": _as_str(rate.get("Status")).upper() != "DELETED",
			})
	row["xeroTaxCodesJson"] = json.dumps(out)
	_persist_integration_record(provider, row)
	return {"ok": True, "provider": provider, "taxCodes": out, "count": len(out)}


@frappe.whitelist(methods=["GET", "POST"])
def list_tax_mappings(**kwargs):
	provider = _as_str(kwargs.get("provider") or kwargs.get("integration_provider") or "Xero")
	row = _integration_record(provider if provider in PROVIDERS else "Xero")
	mappings = _as_mapping_rows(row.get("taxMappingsJson"))
	return {"ok": True, "provider": provider, "mappings": mappings}


@frappe.whitelist(methods=["POST"])
def save_tax_mappings(**kwargs):
	provider = _as_str(kwargs.get("provider") or kwargs.get("integration_provider") or "Xero")
	row = _integration_record(provider if provider in PROVIDERS else "Xero")
	mappings = _as_mapping_rows(kwargs.get("mappings"))
	row["taxMappingsJson"] = json.dumps(mappings)
	_persist_integration_record(provider if provider in PROVIDERS else "Xero", row)
	return {"ok": True, "provider": provider, "saved": len(mappings)}


@frappe.whitelist(methods=["POST"])
def import_tracking_categories(**kwargs):
	provider = _normalize_provider_name(kwargs.get("provider") or kwargs.get("integration_provider"), "Xero")
	row = _integration_record(provider)
	out: list[dict[str, Any]] = []
	if provider in {"QuickBooks", "MYOB"}:
		# No first-class tracking categories in this bridge for these providers yet.
		row["xeroTrackingCategoriesJson"] = json.dumps(out)
		_persist_integration_record(provider, row)
		return {"ok": True, "provider": provider, "categories": out, "count": 0, "message": f"{provider} tracking categories are not used in this bridge."}
	row = _xero_apply_site_config_credentials(row)[0]
	row = _xero_refresh_if_needed(row)
	categories = _xero_fetch_tracking_categories(row)
	for cat in categories:
		if not isinstance(cat, dict):
			continue
		options = cat.get("Options") if isinstance(cat.get("Options"), list) else []
		out.append(
			{
				"id": _as_str(cat.get("TrackingCategoryID")),
				"name": _as_str(cat.get("Name")),
				"status": _as_str(cat.get("Status")),
				"options": [
					{
						"id": _as_str(opt.get("TrackingOptionID")) if isinstance(opt, dict) else "",
						"name": _as_str(opt.get("Name")) if isinstance(opt, dict) else "",
						"status": _as_str(opt.get("Status")) if isinstance(opt, dict) else "",
					}
					for opt in options
					if isinstance(opt, dict)
				],
			}
		)
	row["xeroTrackingCategoriesJson"] = json.dumps(out)
	_persist_integration_record(provider, row)
	return {"ok": True, "provider": provider, "categories": out, "count": len(out)}


@frappe.whitelist(methods=["GET", "POST"])
def list_tracking_mappings(**kwargs):
	provider = _as_str(kwargs.get("provider") or kwargs.get("integration_provider") or "Xero")
	row = _integration_record(provider if provider in PROVIDERS else "Xero")
	mappings = _as_mapping_rows(row.get("trackingMappingsJson"))
	return {"ok": True, "provider": provider, "mappings": mappings}


@frappe.whitelist(methods=["POST"])
def save_tracking_mappings(**kwargs):
	provider = _as_str(kwargs.get("provider") or kwargs.get("integration_provider") or "Xero")
	row = _integration_record(provider if provider in PROVIDERS else "Xero")
	mappings = _as_mapping_rows(kwargs.get("mappings"))
	row["trackingMappingsJson"] = json.dumps(mappings)
	_persist_integration_record(provider if provider in PROVIDERS else "Xero", row)
	return {"ok": True, "provider": provider, "saved": len(mappings)}


@frappe.whitelist(methods=["POST"])
def import_credit_notes(**kwargs):
	provider = _normalize_provider_name(kwargs.get("provider") or kwargs.get("integration_provider"), "Xero")
	row = _integration_record(provider)
	row = _xero_apply_site_config_credentials(row)[0]
	row = _xero_refresh_if_needed(row)
	credit_notes = _xero_fetch_credit_notes(row)
	out: list[dict[str, Any]] = []
	for note in credit_notes:
		if not isinstance(note, dict):
			continue
		contact = note.get("Contact") if isinstance(note.get("Contact"), dict) else {}
		out.append(
			{
				"id": _as_str(note.get("CreditNoteID")),
				"number": _as_str(note.get("CreditNoteNumber")),
				"status": _as_str(note.get("Status")),
				"date": _as_str(note.get("Date") or note.get("DateString")),
				"total": _as_float(note.get("Total"), 0.0),
				"customer_name": _as_str(contact.get("Name")),
				"customer_contact_id": _as_str(contact.get("ContactID")),
				"currency": _as_str(note.get("CurrencyCode")),
			}
		)
	row["xeroCreditNotesJson"] = json.dumps(out)
	_persist_integration_record(provider, row)
	return {"ok": True, "provider": provider, "creditNotes": out, "count": len(out)}


@frappe.whitelist(methods=["POST"])
def sync_now(**kwargs):
	provider = _normalize_provider_name(kwargs.get("provider") or kwargs.get("integration_provider"), "Xero")
	entity = _as_str(kwargs.get("entity") or "all").lower()
	results: list[dict[str, Any]] = []
	if entity in {"all", "item"}:
		results.append({"entity": "item", "result": sync_item(provider=provider)})
	if entity in {"all", "customer"}:
		results.append({"entity": "customer", "result": sync_customer(provider=provider)})
	if entity in {"all", "supplier"}:
		results.append({"entity": "supplier", "result": sync_supplier(provider=provider)})
	if entity in {"all", "invoice"}:
		results.append({"entity": "invoice", "result": sync_invoice(provider=provider)})
	if entity in {"all", "payment"}:
		results.append({"entity": "payment", "result": sync_payment(provider=provider)})
	return {"ok": True, "provider": provider, "entity": entity, "results": results, "message": "Accounting sync completed."}


def run_accounting_auto_sync():
	"""Compulsory daily auto sync across all providers/entities.
	This intentionally ignores per-provider toggle flags in tenant UI.
	"""
	providers = ["Xero", "MYOB", "QuickBooks"]
	entities: list[tuple[str, Any]] = [
		("customer", sync_customer),
		("supplier", sync_supplier),
		("invoice", sync_invoice),
		("payment", sync_payment),
		("item", sync_item),
	]
	results: dict[str, Any] = {"ok": True, "mode": "compulsory_daily_all", "ran": [], "skipped": [], "errors": []}

	for provider in providers:
		try:
			row = _integration_record(provider)
		except Exception as exc:
			results["skipped"].append({"provider": provider, "reason": f"record_unavailable: {_as_str(exc)}"})
			continue

		enabled = _as_bool(row.get("enabled"))
		has_any_auth = bool(
			_as_str(row.get("tenantId"))
			or _as_str(row.get("xeroAccessToken"))
			or _as_str(row.get("quickbooksAccessToken"))
			or _as_str(row.get("clientId"))
		)
		if not enabled and not has_any_auth:
			results["skipped"].append({"provider": provider, "reason": "not_enabled_or_not_configured"})
			continue

		for entity, fn in entities:
			try:
				out = fn(provider=provider)
				results["ran"].append({"provider": provider, "entity": entity, "result": out})
			except Exception as exc:
				msg = _as_str(exc)
				lower = msg.lower()
				if (
					"not implemented" in lower
					or "is not implemented yet" in lower
					or "no backend sync endpoint accepted" in lower
				):
					results["skipped"].append({"provider": provider, "entity": entity, "reason": msg or "not_implemented"})
					continue
				results["errors"].append({"provider": provider, "entity": entity, "error": msg})

	if results["errors"]:
		results["ok"] = False
		try:
			frappe.log_error(json.dumps(results, default=str), "Accounting Auto Sync Errors")
		except Exception:
			pass
	return results


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

	# Bridge unavailable: continue into legacy fallback for compatibility.

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


SIGNUP_COUNTRY_MAP = {
	"au": "Australia",
	"aus": "Australia",
	"australia": "Australia",
	"us": "United States",
	"usa": "United States",
	"united states": "United States",
	"uk": "United Kingdom",
	"gb": "United Kingdom",
	"gbr": "United Kingdom",
	"united kingdom": "United Kingdom",
	"canada": "Canada",
	"ca": "Canada",
	"new zealand": "New Zealand",
	"nz": "New Zealand",
	"nzl": "New Zealand",
}

SIGNUP_ALLOWED_COUNTRIES = {
	"Australia",
	"United States",
	"United Kingdom",
	"Canada",
	"New Zealand",
}


def _normalize_signup_country(value: Any) -> str:
	raw = _as_str(value).strip()
	if not raw:
		return ""
	mapped = SIGNUP_COUNTRY_MAP.get(raw.lower())
	if mapped:
		return mapped
	return raw if raw in SIGNUP_ALLOWED_COUNTRIES else ""


def _signup_request_summary(row: dict[str, Any]) -> dict[str, Any]:
	country = (
		_as_str(row.get("country"))
		or _as_str(row.get("company_country"))
		or _as_str(row.get("tenant_country"))
		or _as_str(row.get("signup_country"))
	)
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
		"country": country,
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
	signup_country = _normalize_signup_country(kwargs.get("country") or kwargs.get("company_country"))
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
	if not signup_country:
		frappe.throw(
			"country is required and must be one of: Australia, United States, United Kingdom, Canada, New Zealand",
			frappe.ValidationError,
		)
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

	doc_data: dict[str, Any] = {
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
	field_names = {str(df.fieldname or "") for df in frappe.get_meta("FL Signup Request").fields}
	country_field = _pick_existing_field(
		field_names, ("country", "company_country", "tenant_country", "signup_country")
	)
	if country_field:
		doc_data[country_field] = signup_country

	doc = frappe.get_doc(doc_data)
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


def _haproxy_provision_command_template() -> str:
	return _site_conf_value(*FIRELINK_HAPROXY_PROVISION_COMMAND_CANDIDATES)


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


def _run_haproxy_provision_command(**kwargs) -> dict[str, Any]:
	template = _haproxy_provision_command_template()
	if not template:
		return {"ok": False, "configured": False, "message": "HAProxy command is not configured."}

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
		return {"ok": False, "configured": True, "message": f"HAProxy command template is invalid: {exc}"}

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
		return {"ok": False, "configured": True, "message": f"HAProxy command failed to start: {exc}"}

	output = ((res.stdout or "") + "\n" + (res.stderr or "")).strip()
	if len(output) > 1200:
		output = output[-1200:]
	if res.returncode != 0:
		return {
			"ok": False,
			"configured": True,
			"message": f"HAProxy command failed with exit code {res.returncode}.",
			"details": output,
		}
	return {"ok": True, "configured": True, "message": "HAProxy command completed.", "details": output}


def _should_run_domain_setup(**kwargs) -> bool:
	if _as_bool(kwargs.get("configure_domain")):
		return True
	domain_option = _as_str(kwargs.get("domain_option")).lower()
	if domain_option == "custom":
		return True
	if _as_str(kwargs.get("custom_domain")):
		return True
	return False


def _should_run_haproxy_setup(**kwargs) -> bool:
	if kwargs.get("configure_haproxy") is None:
		return True
	return _as_bool(kwargs.get("configure_haproxy"))


def _attach_haproxy_result(result: dict[str, Any], **kwargs) -> dict[str, Any]:
	if not _should_run_haproxy_setup(**kwargs):
		result["haproxy_status"] = "skipped"
		result["haproxy_message"] = "HAProxy setup not requested."
		return result
	run = _run_haproxy_provision_command(**kwargs)
	if not _as_bool(run.get("configured")):
		result["haproxy_status"] = "skipped"
		result["haproxy_message"] = "HAProxy command not configured; skipped."
		return result
	result["haproxy_status"] = "success" if _as_bool(run.get("ok")) else "failed"
	result["haproxy_message"] = _as_str(run.get("message"))
	details = _as_str(run.get("details"))
	if details:
		result["haproxy_details"] = details
	return result


def _attach_domain_result(result: dict[str, Any], **kwargs) -> dict[str, Any]:
	if not _should_run_domain_setup(**kwargs):
		result["domain_status"] = "skipped"
		result["domain_message"] = "Wildcard/default domain mode: custom domain setup not requested."
		return _attach_haproxy_result(result, **kwargs)
	domain_run = _run_domain_provision_command(**kwargs)
	result["domain_status"] = "success" if _as_bool(domain_run.get("ok")) else "failed"
	result["domain_message"] = _as_str(domain_run.get("message"))
	details = _as_str(domain_run.get("details"))
	if details:
		result["domain_details"] = details
	return _attach_haproxy_result(result, **kwargs)


def _seed_xero_site_config(site_host: str) -> dict[str, Any]:
	host = _normalize_site_host(site_host)
	if not host:
		return {"ok": False, "message": "site_host is required for Xero seed."}
	row = _integration_record("Xero")
	client_id = _as_str(row.get("clientId"))
	client_secret = _as_str(row.get("clientSecret"))
	if not client_id or not client_secret:
		return {"ok": False, "message": "FireLink Xero credentials are empty."}
	pairs = [
		("firtrackpro_xero_client_id", client_id),
		("firtrackpro_xero_client_secret", client_secret),
	]
	for key, value in pairs:
		try:
			res = subprocess.run(
				["bench", "--site", host, "set-config", key, value],
				check=False,
				text=True,
				capture_output=True,
				timeout=120,
				cwd=_sites_root_path(),
			)
		except Exception as exc:
			return {"ok": False, "message": f"Xero seed failed to start for {host}: {exc}"}
		if int(res.returncode or 0) != 0:
			detail = ((res.stdout or "") + "\n" + (res.stderr or "")).strip()
			if len(detail) > 600:
				detail = detail[-600:]
			return {"ok": False, "message": f"Xero seed failed for {host} on key {key}.", "details": detail}
	return {"ok": True, "message": f"Xero credentials seeded for {host}."}


def _attach_xero_seed_result(result: dict[str, Any], site_host: str) -> dict[str, Any]:
	seed = _seed_xero_site_config(site_host)
	result["xero_seed_status"] = "success" if _as_bool(seed.get("ok")) else "failed"
	result["xero_seed_message"] = _as_str(seed.get("message"))
	details = _as_str(seed.get("details"))
	if details:
		result["xero_seed_details"] = details
	return result


def _list_seedable_site_hosts() -> list[str]:
	root = _sites_root_path()
	excluded = {
		"assets",
		"archived_sites",
		"logs",
		"private",
		"public",
		".git",
		"patches.txt",
		"apps.txt",
		"currentsite.txt",
		"common_site_config.json",
	}
	hosts: list[str] = []
	try:
		entries = sorted(os.listdir(root))
	except Exception:
		return hosts
	for entry in entries:
		if entry in excluded:
			continue
		site_dir = os.path.join(root, entry)
		config_path = os.path.join(site_dir, "site_config.json")
		if not os.path.isdir(site_dir) or not os.path.isfile(config_path):
			continue
		if "." not in entry:
			continue
		host = _normalize_site_host(entry)
		if host:
			hosts.append(host)
	return hosts


def _parse_site_hosts_arg(raw_value: Any) -> list[str]:
	if isinstance(raw_value, list | tuple):
		raw_items = [str(v or "").strip() for v in raw_value]
	else:
		raw = _as_str(raw_value)
		raw_items = [part.strip() for part in raw.replace("\n", ",").split(",") if part.strip()]
	hosts: list[str] = []
	seen: set[str] = set()
	for item in raw_items:
		host = _normalize_site_host(item)
		if host and host not in seen:
			seen.add(host)
			hosts.append(host)
	return hosts


def _seed_xero_site_from_firelink(site_host: str) -> dict[str, Any]:
	host = _normalize_site_host(site_host)
	if not host:
		return {"ok": False, "message": "site_host is required."}
	if _is_firelink_local_site():
		return _seed_xero_site_config(host)
	return _firelink_remote_bridge_call(
		"/api/method/firtrackpro.api.integrations.firelink_admin_seed_xero_for_site_bridge",
		_remote_bridge_payload({"site_host": host}),
	)


def _seed_site_defaults_for_host(site_host: str) -> dict[str, Any]:
	host = _normalize_site_host(site_host)
	if not host:
		return {"ok": False, "message": "site_host is required."}
	try:
		res = subprocess.run(
			["bench", "--site", host, "execute", "firtrackpro.api.site_info.seed_site_defaults_once"],
			check=False,
			text=True,
			capture_output=True,
			timeout=600,
			cwd=_sites_root_path(),
		)
	except Exception as exc:
		return {"ok": False, "message": f"Seed failed to start for {host}: {exc}"}

	output = ((res.stdout or "") + "\n" + (res.stderr or "")).strip()
	if len(output) > 1200:
		output = output[-1200:]
	if int(res.returncode or 0) != 0:
		return {
			"ok": False,
			"message": f"Seed command failed for {host} with exit code {res.returncode}.",
			"details": output,
		}
	low = output.lower()
	if "already seeded" in low:
		return {"ok": True, "already_seeded": True, "message": f"Seed already applied for {host}.", "details": output}
	return {"ok": True, "already_seeded": False, "message": f"Seed completed for {host}.", "details": output}


def _seed_site_defaults_from_firelink(site_host: str) -> dict[str, Any]:
	host = _normalize_site_host(site_host)
	if not host:
		return {"ok": False, "message": "site_host is required."}
	if _is_firelink_local_site():
		return _seed_site_defaults_for_host(host)
	return _firelink_remote_bridge_call(
		"/api/method/firtrackpro.api.integrations.firelink_admin_seed_site_bridge",
		_remote_bridge_payload({"site_host": host}),
	)


@frappe.whitelist(methods=["POST"])
def firelink_admin_seed_xero_for_site(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	host = _normalize_site_host(kwargs.get("site_host") or getattr(frappe.local, "site", ""))
	if not host:
		frappe.throw("site_host is required", frappe.ValidationError)
	result = _seed_xero_site_from_firelink(host)
	result["site_host"] = host
	return result


@frappe.whitelist(allow_guest=True, methods=["POST"])
def firelink_admin_seed_xero_for_site_bridge(**kwargs):
	if not _is_valid_bridge_call():
		frappe.throw("Bridge token or approved firetrackpro origin is required", frappe.PermissionError)
	host = _normalize_site_host(kwargs.get("site_host"))
	if not host:
		frappe.throw("site_host is required", frappe.ValidationError)
	result = _seed_xero_site_config(host)
	result["site_host"] = host
	return result


@frappe.whitelist(methods=["POST"])
def firelink_admin_seed_site(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	host = _normalize_site_host(kwargs.get("site_host") or getattr(frappe.local, "site", ""))
	if not host:
		frappe.throw("site_host is required", frappe.ValidationError)
	result = _seed_site_defaults_from_firelink(host)
	result["site_host"] = host
	return result


@frappe.whitelist(allow_guest=True, methods=["POST"])
def firelink_admin_seed_site_bridge(**kwargs):
	if not _is_valid_bridge_call():
		frappe.throw("Bridge token or approved firetrackpro origin is required", frappe.PermissionError)
	host = _normalize_site_host(kwargs.get("site_host"))
	if not host:
		frappe.throw("site_host is required", frappe.ValidationError)
	result = _seed_site_defaults_for_host(host)
	result["site_host"] = host
	return result


def _rotate_xero_credentials_for_sites(site_hosts: list[str]) -> dict[str, Any]:
	results: list[dict[str, Any]] = []
	success = 0
	failed = 0
	for host in site_hosts:
		seed = _seed_xero_site_config(host)
		ok = _as_bool(seed.get("ok"))
		if ok:
			success += 1
		else:
			failed += 1
		results.append(
			{
				"site_host": host,
				"status": "success" if ok else "failed",
				"message": _as_str(seed.get("message")),
				"details": _as_str(seed.get("details")),
			}
		)
	return {
		"ok": failed == 0,
		"total": len(site_hosts),
		"success": success,
		"failed": failed,
		"results": results,
	}


@frappe.whitelist(methods=["POST"])
def firelink_admin_rotate_xero_credentials(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	sites = _parse_site_hosts_arg(kwargs.get("sites"))
	if _is_firelink_local_site():
		target_sites = sites or _list_seedable_site_hosts()
		if not target_sites:
			return {"ok": False, "message": "No tenant sites found to seed.", "total": 0, "success": 0, "failed": 0, "results": []}
		return _rotate_xero_credentials_for_sites(target_sites)
	return _firelink_remote_bridge_call(
		"/api/method/firtrackpro.api.integrations.firelink_admin_rotate_xero_credentials_bridge",
		_remote_bridge_payload({"sites": sites}),
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def firelink_admin_rotate_xero_credentials_bridge(**kwargs):
	if not _is_valid_bridge_call():
		frappe.throw("Bridge token or approved firetrackpro origin is required", frappe.PermissionError)
	sites = _parse_site_hosts_arg(kwargs.get("sites"))
	target_sites = sites or _list_seedable_site_hosts()
	if not target_sites:
		return {"ok": False, "message": "No tenant sites found to seed.", "total": 0, "success": 0, "failed": 0, "results": []}
	return _rotate_xero_credentials_for_sites(target_sites)


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
			result = _attach_domain_result(
				{
					**before,
					"status": "success",
					"message": f"Site {host} is already provisioned.",
				},
				**kwargs,
			)
			return _attach_xero_seed_result(result, host)

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
			result = _attach_domain_result(
				{
					**after,
					"status": "success",
					"message": _as_str(run.get("message")) or f"Site {host} provisioned.",
					"details": _as_str(run.get("details")),
				},
				**kwargs,
			)
			return _attach_xero_seed_result(result, host)
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
				"configure_haproxy": kwargs.get("configure_haproxy"),
				"domain_option": kwargs.get("domain_option"),
				"custom_domain": kwargs.get("custom_domain"),
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
		result = _attach_domain_result(
			{
				**before,
				"status": "success",
				"message": f"Site {host} is already provisioned.",
			},
			**kwargs,
		)
		return _attach_xero_seed_result(result, host)

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
		result = _attach_domain_result(
			{
				**after,
				"status": "success",
				"message": _as_str(run.get("message")) or f"Site {host} provisioned.",
				"details": _as_str(run.get("details")),
			},
			**kwargs,
		)
		return _attach_xero_seed_result(result, host)
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
	incoming_sticker_id = _as_str(payload.get("firelink_sticker_id"))
	incoming_front_image = _as_str(payload.get("property_front_image"))

	if frappe.db.exists("FL Property", property_id):
		doc = frappe.get_doc("FL Property", property_id)
		doc.property_display_name = display_name
		doc.property_address_json = json.dumps(address_json, separators=(",", ":"))
		doc.property_lat = lat
		doc.property_lng = lng
		if hasattr(doc, "firelink_sticker_id"):
			current_sticker_id = _as_str(getattr(doc, "firelink_sticker_id", ""))
			if incoming_sticker_id and (not current_sticker_id or incoming_sticker_id == current_sticker_id):
				doc.firelink_sticker_id = incoming_sticker_id
		if hasattr(doc, "property_front_image") and incoming_front_image:
			doc.property_front_image = incoming_front_image
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
				"firelink_sticker_id": incoming_sticker_id or None,
				"property_front_image": incoming_front_image or None,
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
			"firelink_sticker_id": _as_str(getattr(doc, "firelink_sticker_id", "")) or None,
			"property_front_image": _as_str(getattr(doc, "property_front_image", "")) or None,
		}
	)
	return {
		"firelink_property_id": firelink_property_id,
		"firelink_ft_property_id": ft_property_id or None,
		"firelink_address_id": address_id,
		"firelink_sticker_id": _as_str(getattr(doc, "firelink_sticker_id", "")) or None,
		"property_front_image": _as_str(getattr(doc, "property_front_image", "")) or None,
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
		if meta.has_field(fieldname) and value is not None and len(str(value)) > 0:
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
	set_if("firelink_sticker_id", _as_str(payload.get("firelink_sticker_id")))
	set_if("property_front_image", _as_str(payload.get("property_front_image")))

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
		"asset_make": _as_str(payload.get("asset_make")),
		"asset_model": _as_str(payload.get("asset_model")),
		"asset_standard": _as_str(payload.get("asset_standard")),
		"asset_photo": _as_str(payload.get("asset_photo")),
		"additional_photos": _as_str(payload.get("additional_photos")),
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
	if not _as_str(payload.get("firelink_defect_id")):
		matched_id = _find_matching_fl_defect_local(payload)
		if matched_id:
			defect_id = matched_id
	if not defect_id:
		frappe.throw("local_defect_id is required", frappe.ValidationError)
	values = {
		"defect_property": property_id,
		"defect_asset": _as_str(payload.get("firelink_asset_id")),
		"defect_template_code": _as_str(payload.get("defect_template_code")),
		"defect_severity": _as_str(payload.get("defect_severity")),
		"defect_status": _as_str(payload.get("defect_status")),
		"defect_summary": _as_str(payload.get("defect_summary"))[:140],
		"defect_notes": _as_str(payload.get("defect_notes")),
		"defect_photo": _as_str(payload.get("defect_photo")),
		"additional_photos": _as_str(payload.get("additional_photos")),
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
		"firelink_sticker_id": _as_str(kwargs.get("firelink_sticker_id")) or None,
		"property_front_image": _as_str(kwargs.get("property_front_image")) or None,
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
	if not _is_firelink_local_site() and _as_str((out or {}).get("firelink_property_id")):
		_upsert_ft_property_local(
			{
				"firelink_property_id": _as_str((out or {}).get("firelink_property_id")),
				"firelink_address_id": firelink_address_id,
				"property_display_name": _as_str(payload.get("property_display_name")) or _as_str(payload.get("address_title")),
				"property_lat": payload.get("property_lat"),
				"property_lng": payload.get("property_lng"),
				"address_line1": _as_str(payload.get("address_line1")),
				"address_line2": _as_str(payload.get("address_line2")),
				"city": _as_str(payload.get("city")),
				"state": _as_str(payload.get("state")),
				"pincode": _as_str(payload.get("pincode")),
				"country": _as_str(payload.get("country")) or "Australia",
				"firelink_sticker_id": _as_str((out or {}).get("firelink_sticker_id")),
				"property_front_image": _as_str((out or {}).get("property_front_image")),
			}
		)
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
		"asset_make": _as_str(kwargs.get("asset_make")) or None,
		"asset_model": _as_str(kwargs.get("asset_model")) or None,
		"asset_standard": _as_str(kwargs.get("asset_standard")) or None,
		"asset_photo": _as_str(kwargs.get("asset_photo")) or None,
		"additional_photos": _as_str(kwargs.get("additional_photos")) or None,
	}
	if _is_firelink_local_site():
		return _upsert_fl_asset_local(payload)
	try:
		result = _firelink_remote_bridge_call(
			"/api/method/firtrackpro.api.integrations.firelink_asset_sync_bridge",
			_remote_bridge_payload(payload),
		)
		_write_back_local_asset_firelink_uid(payload, result)
		return result
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
				"asset_make": _as_str(payload.get("asset_make")),
				"asset_model": _as_str(payload.get("asset_model")),
				"asset_standard": _as_str(payload.get("asset_standard")),
				"asset_photo": _as_str(payload.get("asset_photo")),
				"additional_photos": _as_str(payload.get("additional_photos")),
			},
		)
		result = {"firelink_asset_id": _as_str(remote.get("name")), "created": bool(remote.get("created"))}
		_write_back_local_asset_firelink_uid(payload, result)
		return result


@frappe.whitelist(allow_guest=True, methods=["POST"])
def firelink_asset_sync_bridge(**kwargs):
	if not _is_valid_bridge_call():
		frappe.throw("Bridge token or approved firetrackpro origin is required", frappe.PermissionError)
	return _upsert_fl_asset_local(kwargs)


def _write_back_local_asset_firelink_uid(payload: dict[str, Any], result: dict[str, Any] | None) -> None:
	"""Persist returned FireLink asset uid onto local FT Asset for stable source-of-truth mapping."""
	try:
		firelink_asset_id = _as_str((result or {}).get("firelink_asset_id") or (result or {}).get("name"))
		if not firelink_asset_id:
			return
		local_asset_id = _as_str(payload.get("local_asset_id"))
		if local_asset_id and frappe.db.exists("FT Asset", local_asset_id):
			current_uid = _as_str(frappe.db.get_value("FT Asset", local_asset_id, "asset_firelink_uid"))
			if current_uid != firelink_asset_id:
				frappe.db.set_value("FT Asset", local_asset_id, "asset_firelink_uid", firelink_asset_id, update_modified=False)
				frappe.db.commit()
			return

		asset_identifier = _as_str(payload.get("asset_identifier"))
		asset_label = _as_str(payload.get("asset_label"))
		asset_serial = _as_str(payload.get("asset_serial"))
		firelink_property_id = _as_str(payload.get("firelink_property_id"))
		local_property = ""
		if firelink_property_id and frappe.db.has_column("FT Property", "firelink_uid"):
			local_property = _as_str(frappe.db.get_value("FT Property", {"firelink_uid": firelink_property_id}, "name"))

		candidates = []
		if local_property and asset_identifier:
			candidates = frappe.get_all(
				"FT Asset",
				filters={"asset_property": local_property, "asset_identifier": asset_identifier},
				fields=["name", "asset_firelink_uid"],
				limit_page_length=2,
			)
		if not candidates and local_property and asset_label:
			filters = {"asset_property": local_property, "asset_label": asset_label}
			if asset_serial:
				filters["asset_serial"] = asset_serial
			candidates = frappe.get_all("FT Asset", filters=filters, fields=["name", "asset_firelink_uid"], limit_page_length=2)
		if len(candidates) == 1:
			row = candidates[0]
			current_uid = _as_str(row.get("asset_firelink_uid"))
			if current_uid != firelink_asset_id:
				frappe.db.set_value("FT Asset", row.get("name"), "asset_firelink_uid", firelink_asset_id, update_modified=False)
				frappe.db.commit()
	except Exception:
		return


def _resolve_defect_asset_firelink_id(raw_asset_id: str, local_defect_id: str) -> str:
	asset_id = _as_str(raw_asset_id)
	defect_id = _as_str(local_defect_id)
	if _is_firelink_local_site():
		return asset_id

	# If caller passed a local FT Asset name, map it to the canonical FireLink uid.
	if asset_id and frappe.db.exists("FT Asset", asset_id):
		mapped = _as_str(frappe.db.get_value("FT Asset", asset_id, "asset_firelink_uid"))
		if mapped:
			return mapped

	# If caller passed no usable asset id, use defect->asset->asset_firelink_uid.
	if defect_id and frappe.db.exists("FT Defect", defect_id):
		defect_asset = _as_str(frappe.db.get_value("FT Defect", defect_id, "defect_asset"))
		if defect_asset:
			mapped = _as_str(frappe.db.get_value("FT Asset", defect_asset, "asset_firelink_uid"))
			if mapped:
				return mapped
			frappe.throw(
				f"Defect {defect_id} is linked to local asset {defect_asset}, but that asset has no asset_firelink_uid. "
				"Sync the asset to FireLink first so strict asset linkage is preserved.",
				frappe.ValidationError,
			)
	return asset_id


def _resolve_defect_firelink_id(raw_defect_id: str, local_defect_id: str) -> str:
	defect_id = _as_str(raw_defect_id)
	local_id = _as_str(local_defect_id)
	if defect_id:
		return defect_id
	if local_id and frappe.db.exists("FT Defect", local_id):
		mapped = _as_str(frappe.db.get_value("FT Defect", local_id, "defect_firelink_uid"))
		if mapped:
			return mapped
	return ""


def _writeback_defect_firelink_uid(local_defect_id: str, firelink_defect_id: str) -> None:
	local_id = _as_str(local_defect_id)
	firelink_id = _as_str(firelink_defect_id)
	if (
		not local_id
		or not firelink_id
		or not frappe.db.exists("FT Defect", local_id)
		or not frappe.db.has_column("FT Defect", "defect_firelink_uid")
	):
		return
	try:
		current = _as_str(frappe.db.get_value("FT Defect", local_id, "defect_firelink_uid"))
		if current != firelink_id:
			frappe.db.set_value("FT Defect", local_id, "defect_firelink_uid", firelink_id, update_modified=False)
			frappe.db.commit()
	except Exception:
		return


def _find_matching_fl_defect_local(payload: dict[str, Any]) -> str:
	property_id = _as_str(payload.get("firelink_property_id"))
	asset_id = _as_str(payload.get("firelink_asset_id"))
	summary = _as_str(payload.get("defect_summary"))[:140]
	notes = _as_str(payload.get("defect_notes"))
	if not property_id:
		return ""
	filters = {"defect_property": property_id}
	candidates = frappe.get_all(
		"FL Defect",
		filters=filters,
		fields=["name", "defect_asset", "defect_summary", "defect_notes"],
		limit_page_length=50,
		order_by="modified desc",
	)
	for row in candidates:
		row_summary = _as_str(row.get("defect_summary"))[:140]
		row_notes = _as_str(row.get("defect_notes"))
		row_asset = _as_str(row.get("defect_asset"))
		asset_match = True if not asset_id else (row_asset == asset_id or not row_asset)
		notes_match = True if not notes else (row_notes == notes)
		if row_summary == summary and asset_match and notes_match:
			return _as_str(row.get("name"))
	return ""


@frappe.whitelist(methods=["POST"])
def firelink_defect_sync(**kwargs):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	local_defect_id = _as_str(kwargs.get("local_defect_id"))
	resolved_firelink_asset_id = _resolve_defect_asset_firelink_id(
		_as_str(kwargs.get("firelink_asset_id")),
		local_defect_id,
	)
	payload = {
		"firelink_property_id": _as_str(kwargs.get("firelink_property_id")),
		"firelink_defect_id": _resolve_defect_firelink_id(
			_as_str(kwargs.get("firelink_defect_id")),
			local_defect_id,
		)
		or None,
		"local_defect_id": local_defect_id,
		"firelink_asset_id": resolved_firelink_asset_id or None,
		"defect_template_code": _as_str(kwargs.get("defect_template_code")) or None,
		"defect_severity": _as_str(kwargs.get("defect_severity")) or None,
		"defect_status": _as_str(kwargs.get("defect_status")) or None,
		"defect_summary": _as_str(kwargs.get("defect_summary"))[:140] or None,
		"defect_notes": _as_str(kwargs.get("defect_notes")) or None,
		"defect_photo": _as_str(kwargs.get("defect_photo")) or None,
		"additional_photos": _as_str(kwargs.get("additional_photos")) or None,
	}
	if _is_firelink_local_site():
		out = _upsert_fl_defect_local(payload)
		_writeback_defect_firelink_uid(local_defect_id, _as_str(out.get("firelink_defect_id")))
		return out
	try:
		out = _firelink_remote_bridge_call(
			"/api/method/firtrackpro.api.integrations.firelink_defect_sync_bridge",
			_remote_bridge_payload(payload),
		)
		_writeback_defect_firelink_uid(local_defect_id, _as_str(out.get("firelink_defect_id")))
		return out
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
				"defect_notes": _as_str(payload.get("defect_notes")),
				"defect_photo": _as_str(payload.get("defect_photo")),
				"additional_photos": _as_str(payload.get("additional_photos")),
			},
		)
		out = {"firelink_defect_id": _as_str(remote.get("name")), "created": bool(remote.get("created"))}
		_writeback_defect_firelink_uid(local_defect_id, _as_str(out.get("firelink_defect_id")))
		return out


@frappe.whitelist(allow_guest=True, methods=["POST"])
def firelink_defect_sync_bridge(**kwargs):
	if not _is_valid_bridge_call():
		frappe.throw("Bridge token or approved firetrackpro origin is required", frappe.PermissionError)
	return _upsert_fl_defect_local(kwargs)


def _xero_verify_webhook_signature(raw_body: bytes, signature_header: str, webhook_key: str) -> bool:
	if not raw_body or not signature_header or not webhook_key:
		return False
	computed = base64.b64encode(hmac.new(webhook_key.encode("utf-8"), raw_body, hashlib.sha256).digest()).decode("utf-8")
	return hmac.compare_digest(computed, signature_header)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def xero_webhook(**kwargs):
	"""Xero webhook receiver supporting intent validation and event delivery."""
	row = _integration_record("Xero")
	webhook_key = _as_str(row.get("webhookSecret") or row.get("xeroWebhookKey") or frappe.conf.get("xero_webhook_key"))
	signature = _as_str(getattr(frappe.request, "headers", {}).get("x-xero-signature"))
	raw_body = frappe.request.get_data(cache=False, as_text=False) or b""

	if not _xero_verify_webhook_signature(raw_body, signature, webhook_key):
		frappe.local.response["http_status_code"] = 401
		return {"ok": False, "message": "Invalid Xero webhook signature."}

	# Signature valid: this is enough for Xero Intent-to-Receive handshake.
	payload = {}
	try:
		payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
	except Exception:
		payload = {}

	events = payload.get("events") if isinstance(payload, dict) else None
	if isinstance(events, list) and events:
		frappe.logger("xero_webhook").info({"events": events})

	frappe.local.response["http_status_code"] = 200
	return {"ok": True}


ACCOUNTING_ONBOARDING_KEY = "firtrackpro:accounting_onboarding_settings"


def _load_accounting_onboarding_settings() -> dict[str, Any]:
	raw = _as_str(frappe.db.get_default(ACCOUNTING_ONBOARDING_KEY))
	data = _safe_json_load(raw)
	mode = _as_str(data.get("mode")).lower()
	if mode not in {"erpnext_default", "import_xero", "import_myob", "hybrid"}:
		mode = "erpnext_default"
	status = _as_str(data.get("last_run_status")).lower()
	if status not in {"idle", "ok", "error"}:
		status = "idle"
	return {
		"mode": mode,
		"last_run_at": _as_str(data.get("last_run_at")),
		"last_run_status": status,
		"last_run_message": _as_str(data.get("last_run_message")),
	}


def _save_accounting_onboarding_settings(settings: dict[str, Any]) -> dict[str, Any]:
	normalized = {
		"mode": _as_str(settings.get("mode")) or "erpnext_default",
		"last_run_at": _as_str(settings.get("last_run_at")),
		"last_run_status": _as_str(settings.get("last_run_status")) or "idle",
		"last_run_message": _as_str(settings.get("last_run_message")),
	}
	frappe.db.set_default(ACCOUNTING_ONBOARDING_KEY, json.dumps(normalized))
	return normalized


@frappe.whitelist()
def get_accounting_onboarding_settings():
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	return _load_accounting_onboarding_settings()


@frappe.whitelist(methods=["POST"])
def set_accounting_onboarding_settings(mode: str | None = None):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	next_mode = _as_str(mode).lower()
	if next_mode not in {"erpnext_default", "import_xero", "import_myob", "hybrid"}:
		next_mode = "erpnext_default"
	settings = _load_accounting_onboarding_settings()
	settings["mode"] = next_mode
	return _save_accounting_onboarding_settings(settings)


@frappe.whitelist(methods=["POST"])
def run_accounting_onboarding_setup(mode: str | None = None):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)

	settings = set_accounting_onboarding_settings(mode)
	run_mode = _as_str(settings.get("mode")).lower() or "erpnext_default"
	details: list[str] = []

	try:
		if run_mode in {"import_xero", "hybrid"}:
			coa = import_chart_of_accounts(provider="Xero")
			tax = import_tax_codes(provider="Xero")
			tracking = import_tracking_categories(provider="Xero")
			coa_count = len(coa.get("accounts", [])) if isinstance(coa, dict) else 0
			tax_count = len(tax.get("taxCodes", [])) if isinstance(tax, dict) else 0
			tracking_count = len(tracking.get("tracking", [])) if isinstance(tracking, dict) else 0
			details.append(f"Xero COA imported: {coa_count}")
			details.append(f"Xero tax codes imported: {tax_count}")
			details.append(f"Xero tracking categories imported: {tracking_count}")
		elif run_mode == "import_myob":
			frappe.throw("MYOB onboarding setup is not implemented yet.", frappe.ValidationError)
		else:
			details.append("Using ERPNext default COA mode (no external import).")

		settings["last_run_status"] = "ok"
		settings["last_run_message"] = " | ".join(details) if details else "Accounting onboarding setup completed."
	except Exception as exc:
		settings["last_run_status"] = "error"
		settings["last_run_message"] = _as_str(exc)
	finally:
		settings["last_run_at"] = _utc_iso_now()

	return _save_accounting_onboarding_settings(settings)
