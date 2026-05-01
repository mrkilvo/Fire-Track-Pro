import json
import uuid
from difflib import SequenceMatcher
from datetime import datetime, timezone
from urllib.parse import urlparse

import frappe
from frappe.utils import random_string

STORE_KEY = "firtrackpro:partner_links_json"
STORE_HANDOVERS_KEY = "firtrackpro:partner_handovers_json"
STORE_REQUESTS_KEY = "firtrackpro:partner_link_requests_json"

FIRETRACK_SUFFIX = "firetrackpro.com.au"


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_json_list(store_key):
    raw = str(frappe.db.get_default(store_key) or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _save_json_list(store_key, rows):
    frappe.db.set_default(store_key, json.dumps(rows))


def _load_links():
    return _load_json_list(STORE_KEY)


def _save_links(rows):
    _save_json_list(STORE_KEY, rows)


def _load_handovers():
    return _load_json_list(STORE_HANDOVERS_KEY)


def _save_handovers(rows):
    _save_json_list(STORE_HANDOVERS_KEY, rows)


def _load_requests():
    return _load_json_list(STORE_REQUESTS_KEY)


def _save_requests(rows):
    _save_json_list(STORE_REQUESTS_KEY, rows)


def _normalize_host(value):
    host = str(value or "").strip().lower()
    if host.startswith("http://") or host.startswith("https://"):
        parsed = urlparse(host)
        return str(parsed.hostname or "").strip().lower()
    return host


def _normalize_tenant_input(value):
    host = _normalize_host(value)
    if not host:
        return ""
    if "." not in host:
        return "{0}.{1}".format(host, FIRETRACK_SUFFIX)
    return host


def _site_host():
    return _normalize_host(frappe.utils.get_url())


def _primary_company_name():
    try:
        row = frappe.db.get_value("Company", {}, ["name", "company_name"], as_dict=True)
        if isinstance(row, dict):
            return str(row.get("company_name") or row.get("name") or "").strip()
        if row:
            return str(row).strip()
    except Exception:
        pass
    return ""


def _build_link_row(row):
    return {
        "id": str(row.get("id") or ""),
        "label": str(row.get("label") or ""),
        "tenant_host": str(row.get("tenant_host") or ""),
        "api_base_url": str(row.get("api_base_url") or ""),
        "outbound_api_key": str(row.get("outbound_api_key") or ""),
        "inbound_api_key": str(row.get("inbound_api_key") or ""),
        "status": str(row.get("status") or "active"),
        "notes": str(row.get("notes") or ""),
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
        "supplier": str(row.get("supplier") or ""),
    }

def _primary_company_address():
    company = _primary_company_name()
    if not company:
        return ""
    try:
        links = frappe.get_all(
            "Dynamic Link",
            filters={"link_doctype": "Company", "link_name": company, "parenttype": "Address"},
            fields=["parent"],
            limit_page_length=1,
        )
        if not links:
            return ""
        address_name = str((links[0] or {}).get("parent") or "").strip()
        if not address_name:
            return ""
        addr = frappe.db.get_value("Address", address_name, ["address_line1", "city", "state", "pincode", "country"], as_dict=True)
        if not isinstance(addr, dict):
            return ""
        parts = [
            str(addr.get("address_line1") or "").strip(),
            str(addr.get("city") or "").strip(),
            str(addr.get("state") or "").strip(),
            str(addr.get("pincode") or "").strip(),
            str(addr.get("country") or "").strip(),
        ]
        return ", ".join([x for x in parts if x])
    except Exception:
        return ""



def _build_handover_row(row):
    return {
        "id": str(row.get("id") or ""),
        "job_name": str(row.get("job_name") or ""),
        "job_title": str(row.get("job_title") or ""),
        "partner_link_id": str(row.get("partner_link_id") or ""),
        "partner_label": str(row.get("partner_label") or ""),
        "partner_host": str(row.get("partner_host") or ""),
        "status": str(row.get("status") or "sent"),
        "direction": str(row.get("direction") or "outbound"),
        "partner_job_ref": str(row.get("partner_job_ref") or ""),
        "notes": str(row.get("notes") or ""),
        "source_property_name": str(row.get("source_property_name") or ""),
        "source_property_address": str(row.get("source_property_address") or ""),
        "source_property_firelink_uid": str(row.get("source_property_firelink_uid") or ""),
        "source_tasks": row.get("source_tasks") if isinstance(row.get("source_tasks"), list) else [],
        "source_customer": str(row.get("source_customer") or ""),
        "source_quote_ref": str(row.get("source_quote_ref") or ""),
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
    }


def _build_request_row(row):
    return {
        "id": str(row.get("id") or ""),
        "request_id": str(row.get("request_id") or row.get("id") or ""),
        "from_host": str(row.get("from_host") or ""),
        "from_company": str(row.get("from_company") or ""),
        "to_host": str(row.get("to_host") or ""),
        "to_company": str(row.get("to_company") or ""),
        "status": str(row.get("status") or "pending"),
        "direction": str(row.get("direction") or "outgoing"),
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
        "responded_at": str(row.get("responded_at") or ""),
    }


def _find_link_by_host(host):
    h = _normalize_host(host)
    return next((r for r in _load_links() if _normalize_host(r.get("tenant_host")) == h), None)


def _upsert_link(payload):
    rows = _load_links()
    row_id = str(payload.get("id") or "").strip() or str(uuid.uuid4())
    now = _now_iso()
    idx = -1
    for i, row in enumerate(rows):
        if str(row.get("id") or "") == row_id:
            idx = i
            break
    if idx >= 0:
        payload["created_at"] = str(rows[idx].get("created_at") or now)
        payload["updated_at"] = now
        rows[idx] = payload
    else:
        payload["id"] = row_id
        payload["created_at"] = now
        payload["updated_at"] = now
        rows.append(payload)
    _save_links(rows)
    return payload


def _create_or_update_link_for_request(host, company_name, outbound_key, inbound_key, supplier=""):

    existing = _find_link_by_host(host)
    payload = {
        "id": str((existing or {}).get("id") or ""),
        "label": str((existing or {}).get("label") or company_name or host),
        "tenant_host": _normalize_host(host),
        "api_base_url": str((existing or {}).get("api_base_url") or ""),
        "outbound_api_key": str(outbound_key or (existing or {}).get("outbound_api_key") or ""),
        "inbound_api_key": str(inbound_key or (existing or {}).get("inbound_api_key") or ""),
        "status": "active",
        "notes": str((existing or {}).get("notes") or ""),
        "supplier": str(supplier or (existing or {}).get("supplier") or "").strip(),
    }
    return _upsert_link(payload)




def _find_supplier(company_name, host):
    candidate_names = [str(company_name or "").strip(), str(host or "").strip()]
    for cand in candidate_names:
        if not cand:
            continue
        try:
            row = frappe.db.get_value("Supplier", {"name": cand}, ["name"], as_dict=True)
            if isinstance(row, dict) and row.get("name"):
                return str(row.get("name"))
        except Exception:
            pass
        try:
            row = frappe.db.get_value("Supplier", {"supplier_name": cand}, ["name"], as_dict=True)
            if isinstance(row, dict) and row.get("name"):
                return str(row.get("name"))
        except Exception:
            pass
    return ""


def _ensure_supplier_for_partner(company_name, host):
    existing = _find_supplier(company_name, host)
    if existing:
        return existing

    label = str(company_name or host or "").strip()
    if not label:
        return ""

    options = [
        {"doctype": "Supplier", "supplier_name": label, "supplier_group": "All Supplier Groups", "supplier_type": "Company"},
        {"doctype": "Supplier", "supplier_name": label, "supplier_group": "All Supplier Groups"},
        {"doctype": "Supplier", "supplier_name": label},
    ]
    for payload in options:
        try:
            doc = frappe.get_doc(payload)
            doc.insert(ignore_permissions=True)
            frappe.db.commit()
            return str(doc.name or "")
        except Exception:
            frappe.db.rollback()
            continue
    return ""


def _supplier_score(label, company_name, host):
    label_norm = str(label or "").strip().lower()
    company_norm = str(company_name or "").strip().lower()
    host_norm = str(host or "").strip().lower()
    if not label_norm:
        return 0.0
    candidates = [x for x in [company_norm, host_norm, host_norm.split(".")[0] if host_norm else ""] if x]
    if not candidates:
        return 0.0
    best = 0.0
    for cand in candidates:
        if label_norm == cand:
            return 1.0
        if cand in label_norm or label_norm in cand:
            best = max(best, 0.92)
        best = max(best, SequenceMatcher(None, label_norm, cand).ratio())
    return round(best, 4)


def _suggest_suppliers_for_partner(company_name, host, query=None, limit=12):
    q = str(query or "").strip().lower()
    fields = ["name", "supplier_name"]
    supplier_rows = []
    try:
        if q:
            supplier_rows = frappe.get_all(
                "Supplier",
                fields=fields,
                filters=[["Supplier", "supplier_name", "like", "%{0}%".format(q)]],
                limit_page_length=80,
                order_by="modified desc",
            )
            if len(supplier_rows) < 40:
                more = frappe.get_all(
                    "Supplier",
                    fields=fields,
                    filters=[["Supplier", "name", "like", "%{0}%".format(q)]],
                    limit_page_length=80,
                    order_by="modified desc",
                )
                supplier_rows.extend(more or [])
        else:
            supplier_rows = frappe.get_all("Supplier", fields=fields, limit_page_length=250, order_by="modified desc")
    except Exception:
        supplier_rows = []

    dedup = {}
    for row in supplier_rows or []:
        name = str((row or {}).get("name") or "").strip()
        supplier_name = str((row or {}).get("supplier_name") or "").strip()
        if not name:
            continue
        label = supplier_name or name
        score = _supplier_score(label, company_name, host)
        if q and q not in label.lower() and q not in name.lower():
            continue
        prior = dedup.get(name)
        current = {"name": name, "supplier_name": supplier_name, "score": score}
        if not prior or float(current.get("score") or 0) > float(prior.get("score") or 0):
            dedup[name] = current

    ranked = sorted(dedup.values(), key=lambda x: (float(x.get("score") or 0), str(x.get("supplier_name") or x.get("name") or "").lower()), reverse=True)
    return ranked[: max(1, int(limit or 12))]

def _mark_request_status(request_id, status):
    rows = _load_requests()
    now = _now_iso()
    for row in rows:
        if str(row.get("request_id") or row.get("id") or "") != str(request_id):
            continue
        row["status"] = status
        row["updated_at"] = now
        row["responded_at"] = now
    _save_requests(rows)


@frappe.whitelist(allow_guest=True)
def partner_link_handshake_meta():
    return {
        "ok": True,
        "exists": True,
        "tenant_host": _site_host(),
        "company_name": _primary_company_name(),
        "company_address": _primary_company_address(),
    }


@frappe.whitelist(allow_guest=False)
def list_partner_links():
    return [_build_link_row(row) for row in _load_links() if isinstance(row, dict)]


@frappe.whitelist(allow_guest=False)
def save_partner_link(link=None):
    if not frappe.has_permission("System Settings", "write") and not frappe.has_permission("User", "write"):
        frappe.throw("You do not have permission to manage partner links.")

    if isinstance(link, str):
        try:
            link = json.loads(link)
        except Exception:
            link = {}
    if not isinstance(link, dict):
        link = {}

    label = str(link.get("label") or "").strip()
    tenant_host = _normalize_host(link.get("tenant_host"))
    api_base_url = str(link.get("api_base_url") or "").strip()
    outbound_api_key = str(link.get("outbound_api_key") or "").strip()
    inbound_api_key = str(link.get("inbound_api_key") or "").strip()
    status = str(link.get("status") or "active").strip().lower()
    notes = str(link.get("notes") or "").strip()
    supplier = str(link.get("supplier") or "").strip()
    row_id = str(link.get("id") or "").strip()

    if not label:
        frappe.throw("Label is required.")
    if not tenant_host:
        frappe.throw("Tenant host is required.")
    if status not in {"active", "inactive", "testing"}:
        status = "active"

    payload = {
        "id": row_id,
        "label": label,
        "tenant_host": tenant_host,
        "api_base_url": api_base_url,
        "outbound_api_key": outbound_api_key,
        "inbound_api_key": inbound_api_key,
        "status": status,
        "notes": notes,
        "supplier": supplier,
    }
    return _build_link_row(_upsert_link(payload))


@frappe.whitelist(allow_guest=False)
def delete_partner_link(id=None):
    row_id = str(id or "").strip()
    if not row_id:
        frappe.throw("Partner link id is required.")
    _save_links([row for row in _load_links() if str(row.get("id") or "") != row_id])
    return {"ok": True}


@frappe.whitelist(allow_guest=False)
def test_partner_link(id=None):
    row_id = str(id or "").strip()
    if not row_id:
        frappe.throw("Partner link id is required.")
    row = next((r for r in _load_links() if str(r.get("id") or "") == row_id), None)
    if not row:
        frappe.throw("Partner link was not found.")

    host = str(row.get("tenant_host") or "").strip().lower()
    base = str(row.get("api_base_url") or "").strip() or "https://{0}".format(host)

    import requests

    for url in [
        "{0}/api/method/ping".format(base),
        "{0}/api/method/frappe.auth.get_logged_user".format(base),
    ]:
        try:
            res = requests.get(url, timeout=8)
            if res.status_code in (200, 401, 403):
                return {"ok": True, "message": "Reachable: {0} (HTTP {1})".format(url, res.status_code)}
        except Exception:
            pass

    return {"ok": False, "message": "Unable to reach partner tenant at {0}.".format(base)}




@frappe.whitelist(allow_guest=False)
def verify_partner_tenant(tenant=None):
    raw = str(tenant or "").strip()
    if not raw:
        frappe.throw("Tenant is required.")

    target_host = _normalize_tenant_input(raw)
    if not target_host:
        frappe.throw("Invalid tenant input.")

    if target_host == _site_host():
        frappe.throw("Cannot verify the same tenant.")

    import requests

    target_base = "https://{0}".format(target_host)
    meta_url = "{0}/api/method/firtrackpro.api.partner_links.partner_link_handshake_meta".format(target_base)
    try:
        res = requests.get(meta_url, timeout=12)
        if res.status_code != 200:
            frappe.throw("Tenant exists check failed (HTTP {0}).".format(res.status_code))
        payload = res.json()
        meta = payload.get("message", {}) if isinstance(payload, dict) else {}
    except Exception as exc:
        frappe.throw("Unable to verify tenant host {0}: {1}".format(target_host, exc))

    return {
        "ok": True,
        "tenant_host": target_host,
        "company_name": str(meta.get("company_name") or "").strip(),
        "company_address": str(meta.get("company_address") or "").strip(),
        "message": "Tenant verified.",
    }
@frappe.whitelist(allow_guest=False)
def create_partner_link_request(tenant=None):
    raw = str(tenant or "").strip()
    if not raw:
        frappe.throw("Tenant is required.")

    target_host = _normalize_tenant_input(raw)
    if not target_host:
        frappe.throw("Invalid tenant input.")

    source_host = _site_host()
    if target_host == source_host:
        frappe.throw("Cannot request connection to the same tenant.")

    import requests

    target_base = "https://{0}".format(target_host)
    meta_url = "{0}/api/method/firtrackpro.api.partner_links.partner_link_handshake_meta".format(target_base)
    try:
        meta_res = requests.get(meta_url, timeout=12)
        if meta_res.status_code != 200:
            frappe.throw("Tenant exists check failed (HTTP {0}).".format(meta_res.status_code))
        meta = meta_res.json().get("message", {}) if isinstance(meta_res.json(), dict) else {}
    except Exception as exc:
        frappe.throw("Unable to validate tenant host {0}: {1}".format(target_host, exc))

    target_company = str(meta.get("company_name") or "").strip()
    source_company = _primary_company_name()
    req_id = str(uuid.uuid4())
    now = _now_iso()

    local_row = {
        "id": req_id,
        "request_id": req_id,
        "from_host": source_host,
        "from_company": source_company,
        "to_host": target_host,
        "to_company": target_company,
        "status": "pending",
        "direction": "outgoing",
        "created_at": now,
        "updated_at": now,
        "responded_at": "",
    }
    requests_rows = _load_requests()
    requests_rows.append(local_row)
    _save_requests(requests_rows)

    incoming_url = "{0}/api/method/firtrackpro.api.partner_links.receive_partner_link_request".format(target_base)
    payload = {
        "request_id": req_id,
        "from_host": source_host,
        "from_company": source_company,
        "to_host": target_host,
        "to_company": target_company,
    }
    try:
        incoming_res = requests.post(incoming_url, json=payload, timeout=12)
        if incoming_res.status_code != 200:
            frappe.throw("Target tenant rejected request (HTTP {0}).".format(incoming_res.status_code))
    except Exception as exc:
        frappe.throw("Failed to deliver request to target tenant: {0}".format(exc))

    return {
        "ok": True,
        "message": "Connection request sent to {0}{1}.".format(target_host, " ({0})".format(target_company) if target_company else ""),
        "request": _build_request_row(local_row),
    }


@frappe.whitelist(allow_guest=True)
def receive_partner_link_request(request_id=None, from_host=None, from_company=None, to_host=None, to_company=None):
    rid = str(request_id or "").strip() or str(uuid.uuid4())
    source_host = _normalize_host(from_host)
    now = _now_iso()

    if not source_host:
        frappe.throw("from_host is required.")

    rows = _load_requests()
    if any(str(r.get("request_id") or r.get("id") or "") == rid for r in rows):
        return {"ok": True, "message": "Request already exists."}

    row = {
        "id": rid,
        "request_id": rid,
        "from_host": source_host,
        "from_company": str(from_company or "").strip(),
        "to_host": _normalize_host(to_host) or _site_host(),
        "to_company": str(to_company or _primary_company_name()).strip(),
        "status": "pending",
        "direction": "incoming",
        "created_at": now,
        "updated_at": now,
        "responded_at": "",
    }
    rows.append(row)
    _save_requests(rows)
    return {"ok": True}


@frappe.whitelist(allow_guest=False)
def list_partner_link_requests(direction=None):
    d = str(direction or "").strip().lower()
    out = []
    for row in _load_requests():
        if not isinstance(row, dict):
            continue
        if d and str(row.get("direction") or "").strip().lower() != d:
            continue
        out.append(_build_request_row(row))
    out.sort(key=lambda r: str(r.get("updated_at") or ""), reverse=True)
    return out


@frappe.whitelist(allow_guest=False)
def respond_partner_link_request(id=None, action=None):
    rid = str(id or "").strip()
    act = str(action or "").strip().lower()
    if not rid:
        frappe.throw("Request id is required.")
    if act not in {"accept", "decline", "disconnect"}:
        frappe.throw("Invalid action.")

    rows = _load_requests()
    target = None
    for row in rows:
        if str(row.get("id") or row.get("request_id") or "") != rid:
            continue
        target = row
        break
    if not target:
        frappe.throw("Request not found.")

    source_host = _normalize_host(target.get("from_host"))
    source_company = str(target.get("from_company") or "").strip()
    selected_supplier = str(frappe.form_dict.get("supplier") or "").strip()
    create_new_supplier = str(frappe.form_dict.get("create_new_supplier") or "0").strip().lower() in {"1", "true", "yes"}

    import requests

    if act == "accept":
        incoming_key = random_string(40)
        outgoing_key = random_string(40)

        supplier_name = ""
        if selected_supplier:
            if not frappe.db.exists("Supplier", selected_supplier):
                frappe.throw("Selected supplier does not exist.")
            supplier_name = selected_supplier
        elif create_new_supplier:
            supplier_name = _ensure_supplier_for_partner(source_company, source_host)
            if not supplier_name:
                frappe.throw("Unable to create supplier for this partner.")
        else:
            exact = _find_supplier(source_company, source_host)
            if exact:
                supplier_name = exact
            else:
                frappe.throw("Select an existing supplier or choose create new before accepting.")

        # Local side receives calls signed by remote outgoing_key, and sends using local outgoing_key.
        _create_or_update_link_for_request(source_host, source_company, outbound_key=outgoing_key, inbound_key=incoming_key, supplier=supplier_name)

        finalize_url = "https://{0}/api/method/firtrackpro.api.partner_links.finalize_partner_link_request".format(source_host)
        payload = {
            "request_id": rid,
            # Remote inbound = what remote expects from us.
            # Remote outbound = what remote sends to us.
            "remote_inbound_key": incoming_key,
            "remote_outbound_key": outgoing_key,
            "remote_host": _site_host(),
            "remote_company": _primary_company_name(),
        }
        try:
            res = requests.post(finalize_url, json=payload, timeout=12)
            if res.status_code != 200:
                frappe.throw("Failed finalizing on remote tenant (HTTP {0}).".format(res.status_code))
        except Exception as exc:
            frappe.throw("Failed finalizing request on remote tenant: {0}".format(exc))

        target["status"] = "accepted"
        target["updated_at"] = _now_iso()
        target["responded_at"] = _now_iso()
        _save_requests(rows)
        return {"ok": True, "message": "Request accepted. Link activated and keys exchanged.", "supplier": supplier_name}

    if act == "decline":
        target["status"] = "declined"
        target["updated_at"] = _now_iso()
        target["responded_at"] = _now_iso()
        _save_requests(rows)

        try:
            notify_url = "https://{0}/api/method/firtrackpro.api.partner_links.remote_request_status_update".format(source_host)
            requests.post(notify_url, json={"request_id": rid, "status": "declined"}, timeout=8)
        except Exception:
            pass

        return {"ok": True, "message": "Request declined."}

    # disconnect
    link = _find_link_by_host(source_host)
    if link:
        link["status"] = "inactive"
        _upsert_link(link)
    target["status"] = "disconnected"
    target["updated_at"] = _now_iso()
    target["responded_at"] = _now_iso()
    _save_requests(rows)

    try:
        notify_url = "https://{0}/api/method/firtrackpro.api.partner_links.remote_request_status_update".format(source_host)
        requests.post(notify_url, json={"request_id": rid, "status": "disconnected"}, timeout=8)
    except Exception:
        pass

    return {"ok": True, "message": "Connection disconnected."}


@frappe.whitelist(allow_guest=True)
def finalize_partner_link_request(request_id=None, remote_inbound_key=None, remote_outbound_key=None, remote_host=None, remote_company=None):
    rid = str(request_id or "").strip()
    if not rid:
        frappe.throw("request_id is required.")

    rows = _load_requests()
    target = None
    for row in rows:
        if str(row.get("request_id") or row.get("id") or "") == rid:
            target = row
            break
    if not target:
        frappe.throw("Request not found.")

    # remote_inbound_key is the key remote expects from us -> our outbound key
    # remote_outbound_key is the key remote will send to us -> our inbound key
    host = _normalize_host(remote_host or target.get("to_host") or target.get("from_host"))
    company_name = str(remote_company or target.get("to_company") or "").strip()

    supplier_name = _ensure_supplier_for_partner(company_name, host)
    _create_or_update_link_for_request(host, company_name, outbound_key=str(remote_inbound_key or ""), inbound_key=str(remote_outbound_key or ""), supplier=supplier_name)

    target["status"] = "accepted"
    target["updated_at"] = _now_iso()
    target["responded_at"] = _now_iso()
    _save_requests(rows)
    return {"ok": True}


@frappe.whitelist(allow_guest=True)
def remote_request_status_update(request_id=None, status=None):
    rid = str(request_id or "").strip()
    st = str(status or "").strip().lower()
    if not rid:
        return {"ok": False}
    if st not in {"declined", "disconnected", "accepted"}:
        return {"ok": False}
    _mark_request_status(rid, st)
    return {"ok": True}




@frappe.whitelist(allow_guest=False)
def get_partner_link_supplier(partner_link_id=None, ensure=1):
    link_id = str(partner_link_id or "").strip()
    if not link_id:
        frappe.throw("partner_link_id is required.")
    links = _load_links()
    target = next((r for r in links if str(r.get("id") or "") == link_id), None)
    if not target:
        frappe.throw("Partner link not found.")

    supplier = str(target.get("supplier") or "").strip()
    if supplier:
        return {"ok": True, "supplier": supplier}

    if str(ensure or "1") in {"0", "false", "False"}:
        return {"ok": True, "supplier": ""}

    supplier = _ensure_supplier_for_partner(str(target.get("label") or "").strip(), str(target.get("tenant_host") or "").strip())
    if supplier:
        target["supplier"] = supplier
        _upsert_link(target)
    return {"ok": True, "supplier": supplier}


@frappe.whitelist(allow_guest=False)
def suggest_partner_link_suppliers(request_id=None, query=None):
    rid = str(request_id or "").strip()
    if not rid:
        frappe.throw("request_id is required.")
    rows = _load_requests()
    target = next((row for row in rows if str(row.get("id") or row.get("request_id") or "") == rid), None)
    if not target:
        frappe.throw("Request not found.")

    source_host = _normalize_host(target.get("from_host"))
    source_company = str(target.get("from_company") or "").strip()
    candidates = _suggest_suppliers_for_partner(source_company, source_host, query=query, limit=14)
    return {
        "ok": True,
        "host": source_host,
        "company_name": source_company,
        "candidates": candidates,
    }

@frappe.whitelist(allow_guest=False)
def create_handover_job(job_name=None, partner_link_id=None, notes=None):
    job_id = str(job_name or "").strip()
    link_id = str(partner_link_id or "").strip()
    if not job_id:
        frappe.throw("job_name is required.")
    if not link_id:
        frappe.throw("partner_link_id is required.")

    link = next((r for r in _load_links() if str(r.get("id") or "") == link_id), None)
    if not link:
        frappe.throw("Partner link was not found.")
    if str(link.get("status") or "active") == "inactive":
        frappe.throw("Partner link is inactive.")

    job_doc = frappe.get_doc("FT Job", job_id)
    source_property_name = ""
    source_property_address = ""
    source_customer = str(
        getattr(job_doc, "job_customer", None)
        or getattr(job_doc, "customer", None)
        or getattr(job_doc, "property_customer", None)
        or ""
    ).strip()
    source_quote_ref = str(
        getattr(job_doc, "job_quote", None)
        or getattr(job_doc, "quotation", None)
        or getattr(job_doc, "quote", None)
        or ""
    ).strip()
    source_property = str(
        getattr(job_doc, "job_property", None)
        or getattr(job_doc, "property", None)
        or getattr(job_doc, "job_property_name", None)
        or ""
    ).strip()
    source_property_firelink_uid = ""
    source_tasks = []
    if source_property:
        try:
            prop = frappe.db.get_value(
                "FT Property",
                source_property,
                [
                    "name",
                    "property_name",
                    "property_title",
                    "property_address",
                    "address",
                    "primary_address",
                    "property_customer",
                    "customer",
                ],
                as_dict=True,
            )
            if isinstance(prop, dict):
                source_property_name = str(prop.get("name") or prop.get("property_name") or prop.get("property_title") or source_property).strip()
                source_property_address = str(
                    prop.get("property_address")
                    or prop.get("address")
                    or prop.get("primary_address")
                    or ""
                ).strip()
                source_property_firelink_uid = str(
                    prop.get("firelink_uid")
                    or prop.get("firelink_property_uid")
                    or prop.get("property_uid")
                    or ""
                ).strip()
                if not source_customer:
                    source_customer = str(prop.get("property_customer") or prop.get("customer") or "").strip()
        except Exception:
            source_property_name = source_property
    try:
        task_rows = list(getattr(job_doc, "job_tasks", None) or [])
        for tr in task_rows:
            if not tr:
                continue
            title = str(
                getattr(tr, "task_name", None)
                or getattr(tr, "title", None)
                or getattr(tr, "description", None)
                or getattr(tr, "task", None)
                or ""
            ).strip()
            status = str(getattr(tr, "status", None) or "").strip()
            item_code = str(getattr(tr, "item_code", None) or "").strip()
            qty = getattr(tr, "qty", None)
            if not title and not item_code:
                continue
            source_tasks.append(
                {
                    "title": title,
                    "status": status,
                    "item_code": item_code,
                    "qty": float(qty) if qty not in (None, "") else None,
                }
            )
    except Exception:
        source_tasks = []

    now = _now_iso()
    row = {
        "id": str(uuid.uuid4()),
        "job_name": job_id,
        "job_title": str(getattr(job_doc, "job_title", "") or "").strip(),
        "partner_link_id": link_id,
        "partner_label": str(link.get("label") or "").strip(),
        "partner_host": str(link.get("tenant_host") or "").strip(),
        "status": "sent",
        "direction": "outbound",
        "partner_job_ref": "",
        "notes": str(notes or "").strip(),
        "source_property_name": source_property_name,
        "source_property_address": source_property_address,
        "source_property_firelink_uid": source_property_firelink_uid,
        "source_tasks": source_tasks,
        "source_customer": source_customer,
        "source_quote_ref": source_quote_ref,
        "created_at": now,
        "updated_at": now,
    }

    rows = _load_handovers()
    rows.append(row)
    _save_handovers(rows)

    _push_handover_to_partner(link, row)

    return _build_handover_row(row)


def _push_handover_to_partner(link, row):
    host = str(link.get("tenant_host") or "").strip().lower()
    base = str(link.get("api_base_url") or "").strip() or "https://{0}".format(host)
    outbound_api_key = str(link.get("outbound_api_key") or "").strip()
    if not base:
        return

    import requests

    headers = {"Content-Type": "application/json"}
    if outbound_api_key:
        headers["X-FireTrack-Partner-Key"] = outbound_api_key

    source_tasks = row.get("source_tasks") if isinstance(row.get("source_tasks"), list) else []
    source_property_firelink_uid = str(row.get("source_property_firelink_uid") or "").strip()

    payload = {
        "handover_id": row.get("id"),
        "source_job_name": row.get("job_name"),
        "source_job_title": row.get("job_title"),
        "source_tenant_host": _site_host(),
        "notes": row.get("notes") or "",
        "source_property_name": row.get("source_property_name") or "",
        "source_property_address": row.get("source_property_address") or "",
        "source_property_firelink_uid": source_property_firelink_uid,
        "source_tasks": source_tasks,
        "source_customer": row.get("source_customer") or "",
        "source_quote_ref": row.get("source_quote_ref") or "",
        "partner_link_id": row.get("partner_link_id") or "",
    }

    try:
        res = requests.post(
            "{0}/api/method/firtrackpro.api.partner_links.receive_handover_job".format(base.rstrip("/")),
            json=payload,
            headers=headers,
            timeout=15,
        )
        if res.status_code == 200:
            try:
                data = res.json()
                partner_ref = str((data or {}).get("message", {}).get("partner_job_ref") or "").strip()
            except Exception:
                partner_ref = ""
            if partner_ref:
                rows = _load_handovers()
                for item in rows:
                    if str(item.get("id") or "") == str(row.get("id") or ""):
                        item["partner_job_ref"] = partner_ref
                        item["updated_at"] = _now_iso()
                _save_handovers(rows)
        else:
            body = ""
            try:
                body = str(res.text or "").strip()
            except Exception:
                body = ""
            detail = "Partner API HTTP {0}".format(res.status_code)
            if body:
                detail = "{0}: {1}".format(detail, body[:1200])
            _mark_handover_failed(str(row.get("id") or ""), detail)
    except Exception as exc:
        _mark_handover_failed(str(row.get("id") or ""), "Partner push failed: {0}".format(exc))


def _mark_handover_failed(handover_id, error_text):
    rows = _load_handovers()
    for item in rows:
        if str(item.get("id") or "") == str(handover_id):
            item["status"] = "failed"
            base_notes = str(item.get("notes") or "").strip()
            item["notes"] = (base_notes + "\n" if base_notes else "") + str(error_text or "")
            item["updated_at"] = _now_iso()
    _save_handovers(rows)


@frappe.whitelist(allow_guest=True)
def receive_handover_job(
    handover_id=None,
    source_job_name=None,
    source_job_title=None,
    source_tenant_host=None,
    notes=None,
    partner_link_id=None,
    source_property_name=None,
    source_property_address=None,
    source_property_firelink_uid=None,
    source_tasks=None,
    source_customer=None,
    source_quote_ref=None,
):
    provided_key = frappe.get_request_header("X-FireTrack-Partner-Key") or ""
    link = None

    all_links = _load_links()
    if partner_link_id:
        link = next((r for r in all_links if str(r.get("id") or "") == str(partner_link_id)), None)
    if not link and source_tenant_host:
        host = _normalize_host(source_tenant_host)
        link = next((r for r in all_links if str(r.get("tenant_host") or "") == host), None)
    if not link:
        frappe.throw("Partner link not found.")

    inbound_key = str(link.get("inbound_api_key") or "").strip()
    if inbound_key and inbound_key != str(provided_key or "").strip():
        frappe.throw("Unauthorized partner key.")

    now = _now_iso()
    parsed_tasks = []
    if isinstance(source_tasks, list):
        parsed_tasks = source_tasks
    elif isinstance(source_tasks, str) and source_tasks.strip():
        try:
            candidate = json.loads(source_tasks)
            if isinstance(candidate, list):
                parsed_tasks = candidate
        except Exception:
            parsed_tasks = []

    incoming = {
        "id": str(handover_id or uuid.uuid4()),
        "job_name": str(source_job_name or "").strip(),
        "job_title": str(source_job_title or "").strip(),
        "partner_link_id": str(link.get("id") or "").strip(),
        "partner_label": str(link.get("label") or "").strip(),
        "partner_host": str(source_tenant_host or link.get("tenant_host") or "").strip(),
        "status": "sent",
        "direction": "inbound",
        "partner_job_ref": "",
        "notes": str(notes or "").strip(),
        "source_property_name": str(source_property_name or "").strip(),
        "source_property_address": str(source_property_address or "").strip(),
        "source_property_firelink_uid": str(source_property_firelink_uid or "").strip(),
        "source_tasks": parsed_tasks,
        "source_customer": str(source_customer or "").strip(),
        "source_quote_ref": str(source_quote_ref or "").strip(),
        "created_at": now,
        "updated_at": now,
    }

    rows = _load_handovers()
    if not any(str(r.get("id") or "") == incoming["id"] for r in rows):
        rows.append(incoming)
        _save_handovers(rows)

    return {"ok": True, "partner_job_ref": incoming["id"]}


@frappe.whitelist(allow_guest=False)
def list_handover_jobs(direction=None, status=None, job_name=None):
    direction_filter = str(direction or "").strip().lower()
    status_filter = str(status or "").strip().lower()
    job_filter = str(job_name or "").strip()

    out = []
    for row in _load_handovers():
        if not isinstance(row, dict):
            continue
        if direction_filter and str(row.get("direction") or "").strip().lower() != direction_filter:
            continue
        if status_filter and str(row.get("status") or "").strip().lower() != status_filter:
            continue
        if job_filter and str(row.get("job_name") or "").strip() != job_filter:
            continue
        out.append(_build_handover_row(row))

    out.sort(key=lambda r: str(r.get("updated_at") or ""), reverse=True)
    return out


@frappe.whitelist(allow_guest=False)
def update_handover_job_status(id=None, status=None, notes=None):
    row_id = str(id or "").strip()
    next_status = str(status or "").strip().lower()
    if not row_id:
        frappe.throw("Handover id is required.")
    if next_status not in {"accepted", "rejected", "in_progress", "completed"}:
        frappe.throw("Invalid handover status.")

    rows = _load_handovers()
    target = None
    now = _now_iso()
    for row in rows:
        if str(row.get("id") or "") != row_id:
            continue
        row["status"] = next_status
        row["updated_at"] = now
        if notes is not None:
            row["notes"] = str(notes or "").strip()
        target = row
        break

    if not target:
        frappe.throw("Handover was not found.")

    _save_handovers(rows)
    return _build_handover_row(target)
