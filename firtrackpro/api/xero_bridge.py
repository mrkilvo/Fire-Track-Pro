from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import frappe

from firtrackpro.api.integrations import (
    PROVIDER_DEFAULTS,
    _as_str,
    _firelink_http,
    _firelink_remote_bridge_call,
    _is_firelink_local_site,
    _normalize_site_host,
    _remote_bridge_payload,
    _integration_record,
    _persist_integration_record,
    _xero_redirect_uri,
)


def _site_xero_config() -> dict[str, str]:
    client_id = ""
    client_secret = ""
    for key in (
        "firtrackpro_xero_client_id",
        "xero_client_id",
    ):
        value = _as_str(frappe.conf.get(key))
        if value:
            client_id = value
            break
    for key in (
        "firtrackpro_xero_client_secret",
        "xero_client_secret",
    ):
        value = _as_str(frappe.conf.get(key))
        if value:
            client_secret = value
            break
    return {
        "clientId": client_id,
        "clientSecret": client_secret,
    }


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

    # For tenant sites, always start OAuth via FireLink so only one callback URI is needed in Xero.
    if not _is_firelink_local_site():
        host = _normalize_site_host(getattr(frappe.local, "site", ""))
        if not host:
            frappe.throw("Unable to determine tenant host for Xero connect.", frappe.ValidationError)
        bridge = _firelink_remote_bridge_call(
            "/api/method/firtrackpro.api.integrations.firelink_xero_oauth_start_bridge",
            _remote_bridge_payload({"site_host": host}),
        )
        if isinstance(bridge, dict):
            return bridge
        frappe.throw("Invalid FireLink Xero bridge response", frappe.ValidationError)

    row = _integration_record("Xero")
    site_cfg = _site_xero_config()
    shared = _load_firelink_xero_config()

    client_id = _as_str(
        kwargs.get("client_id")
        or kwargs.get("clientId")
        or row.get("clientId")
        or site_cfg.get("clientId")
        or shared.get("clientId")
    )
    client_secret = _as_str(
        kwargs.get("client_secret")
        or kwargs.get("clientSecret")
        or row.get("clientSecret")
        or site_cfg.get("clientSecret")
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

    if not _as_str(row.get("tokenUrl")) and _as_str(shared.get("tokenUrl")):
        row["tokenUrl"] = _as_str(shared.get("tokenUrl"))
    if not _as_str(row.get("webhookSecret")) and _as_str(shared.get("webhookSecret")):
        row["webhookSecret"] = _as_str(shared.get("webhookSecret"))

    if not client_id or not client_secret:
        frappe.throw(
            "Xero Client ID and Client Secret are required (tenant/site config/FireLink fallback all empty).",
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
