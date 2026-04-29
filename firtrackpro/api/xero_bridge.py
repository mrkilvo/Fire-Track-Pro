from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import frappe

from firtrackpro.api.integrations import (
    PROVIDER_DEFAULTS,
    _as_str,
    _firelink_http,
    _integration_record,
    _persist_integration_record,
    _xero_redirect_uri,
)


def _load_firelink_xero_config() -> dict[str, Any]:
    """Read central Xero config from FireLink source-of-truth."""
    try:
        payload = _firelink_http(
            "GET",
            "/api/method/firtrackpro.api.integrations.list_configs",
        )
    except Exception:
        return {}

    msg = payload.get("message") if isinstance(payload, dict) else {}
    if not isinstance(msg, dict):
        return {}

    records = msg.get("records") if isinstance(msg.get("records"), dict) else {}
    xero = records.get("Xero") if isinstance(records.get("Xero"), dict) else {}
    if not xero:
        return {}

    return {
        "clientId": _as_str(xero.get("clientId")),
        "clientSecret": _as_str(xero.get("clientSecret")),
        "authUrl": _as_str(xero.get("authUrl")),
        "tokenUrl": _as_str(xero.get("tokenUrl")),
        "scopes": _as_str(xero.get("scopes")),
        "webhookSecret": _as_str(xero.get("webhookSecret")),
    }


@frappe.whitelist()
def xero_oauth_start_shared(**kwargs):
    if frappe.session.user == "Guest":
        frappe.throw("Login required", frappe.PermissionError)

    row = _integration_record("Xero")
    shared = _load_firelink_xero_config()

    client_id = _as_str(
        kwargs.get("client_id")
        or kwargs.get("clientId")
        or row.get("clientId")
        or shared.get("clientId")
    )
    client_secret = _as_str(
        kwargs.get("client_secret")
        or kwargs.get("clientSecret")
        or row.get("clientSecret")
        or shared.get("clientSecret")
    )
    auth_url = _as_str(
        kwargs.get("auth_url")
        or kwargs.get("authUrl")
        or row.get("authUrl")
        or shared.get("authUrl")
    ) or _as_str(PROVIDER_DEFAULTS["Xero"].get("authUrl"))
    scopes = _as_str(kwargs.get("scopes") or row.get("scopes") or shared.get("scopes")) or _as_str(
        PROVIDER_DEFAULTS["Xero"].get("scopes")
    )

    # Keep tenant row hydrated with centrally managed values so callback can complete locally.
    if not _as_str(row.get("tokenUrl")) and _as_str(shared.get("tokenUrl")):
        row["tokenUrl"] = _as_str(shared.get("tokenUrl"))
    if not _as_str(row.get("webhookSecret")) and _as_str(shared.get("webhookSecret")):
        row["webhookSecret"] = _as_str(shared.get("webhookSecret"))

    if not client_id or not client_secret:
        frappe.throw(
            "Xero Client ID and Client Secret are required (tenant + FireLink fallback both empty).",
            frappe.ValidationError,
        )
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
    return {
        "ok": True,
        "authorize_url": f"{auth_url}?{urlencode(params)}",
        "state": state,
        "redirect_uri": _xero_redirect_uri(row),
    }
