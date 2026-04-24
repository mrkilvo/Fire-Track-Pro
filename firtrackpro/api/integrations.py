import json
from typing import Any

import frappe

try:
	import requests
except Exception:  # pragma: no cover
	requests = None

PROVIDERS = ["MYOB", "Xero", "QuickBooks", "Custom"]
DEFAULTS_KEY = "firtrackpro:integration_configs_json"

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
