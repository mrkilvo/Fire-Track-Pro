import json

import frappe

try:
	import requests
except Exception:
	requests = None

LIMIT_DEFAULT_KEYS = [
	"firtrackpro:allowed_users",
	"firtrackpro:user_limit",
	"firelink:allowed_users",
]
FIRELINK_BASE_DEFAULT_KEY = "firtrackpro:firelink_base_url"
FIRELINK_ENDPOINT_DEFAULT_KEY = "firtrackpro:firelink_user_limit_endpoint"
CACHED_LIMIT_DEFAULT_KEY = "firtrackpro:cached_allowed_users"
FIRELINK_BASE_FALLBACK = "https://firelink.firetrackpro.com.au"
FIRELINK_ENDPOINT_FALLBACK = "/api/method/firtrackpro.api.membership.get_site_user_quota"
FIRELINK_ENDPOINT_CANDIDATES = [
	"/api/method/firtrackpro.api.membership.get_site_user_quota",
	"/api/method/firetrackpro.api.membership.get_site_user_quota",
	"/api/method/firelink.api.membership.get_site_user_quota",
	"/api/method/firtrackpro.api.membership.get_user_limit",
	"/api/method/firetrackpro.api.membership.get_user_limit",
	"/api/method/firelink.api.membership.get_user_limit",
]

SYSTEM_EXCLUDED_USERS = {"Guest", "Administrator"}


def _to_int_or_none(value):
	if value is None:
		return None
	raw = str(value).strip()
	if not raw:
		return None
	try:
		parsed = int(float(raw))
	except Exception:
		return None
	if parsed < 0:
		return 0
	return parsed


def _is_website_user(doc):
	user_type = str(getattr(doc, "user_type", "") or "").strip().lower()
	return user_type == "website user"


def _count_billable_enabled_users(exclude_user=None):
	rows = frappe.get_all(
		"User",
		filters={"enabled": 1},
		fields=["name", "user_type"],
		limit_page_length=2000,
	)
	out = 0
	excluded = str(exclude_user or "").strip()
	for row in rows:
		name = str(row.get("name") or "").strip()
		if not name or name in SYSTEM_EXCLUDED_USERS:
			continue
		if excluded and name == excluded:
			continue
		user_type = str(row.get("user_type") or "").strip().lower()
		if user_type == "website user":
			continue
		out += 1
	return out


def _candidate_limit_fields(doctype):
	if not frappe.db.exists("DocType", doctype):
		return []
	try:
		meta = frappe.get_meta(doctype)
		out = []
		for field in meta.fields or []:
			fieldname = str(field.fieldname or "").strip()
			if not fieldname:
				continue
			lowered = fieldname.lower()
			if "user" not in lowered and "seat" not in lowered:
				continue
			if not any(key in lowered for key in ["limit", "allowed", "max", "quota", "seat"]):
				continue
			out.append(fieldname)
		return out
	except Exception:
		return []


def _first_limit_from_row(row, fields):
	for fieldname in fields:
		val = _to_int_or_none(row.get(fieldname))
		if val is not None:
			return val, fieldname
	return None, None


def _get_default_limit():
	for key in LIMIT_DEFAULT_KEYS:
		val = _to_int_or_none(frappe.db.get_default(key))
		if val is not None:
			return val, f"site_default:{key}"
	return None, ""


def _get_cached_limit():
	return _to_int_or_none(frappe.db.get_default(CACHED_LIMIT_DEFAULT_KEY))


def _set_cached_limit(limit):
	if limit is None:
		return
	try:
		frappe.db.set_default(CACHED_LIMIT_DEFAULT_KEY, str(int(limit)))
	except Exception:
		pass


def _get_membership_api_key():
	if not frappe.db.exists("DocType", "FL Membership"):
		return ""
	rows = frappe.get_all(
		"FL Membership",
		fields=["name", "membership_status"],
		order_by="modified desc",
		limit_page_length=20,
	)
	for row in rows:
		status = str(row.get("membership_status") or "").strip().lower()
		if status and status != "active":
			continue
		name = str(row.get("name") or "").strip()
		if not name:
			continue
		try:
			doc = frappe.get_doc("FL Membership", name)
			key = str(doc.get_password("membership_api_key") or "").strip()
			if key:
				return key
		except Exception:
			continue
	return ""


def _get_local_membership_limit():
	for doctype in ("FL Membership", "FL Organisation", "FireTrack Pro Settings"):
		if not frappe.db.exists("DocType", doctype):
			continue
		fields = _candidate_limit_fields(doctype)
		if not fields:
			continue
		query_fields = ["name"] + fields
		filters = {}
		if doctype == "FL Membership":
			membership_meta_fields = {str(f.fieldname or "") for f in frappe.get_meta(doctype).fields or []}
			if "membership_status" in membership_meta_fields:
				filters = {"membership_status": "active"}
		rows = frappe.get_all(
			doctype,
			fields=query_fields,
			filters=filters,
			order_by="modified desc",
			limit_page_length=20,
		)
		for row in rows:
			limit, fieldname = _first_limit_from_row(row, fields)
			if limit is not None:
				return limit, f"{doctype}.{fieldname}"
	return None, ""


def _extract_limit_from_payload(payload):
	candidates = [
		payload.get("allowed_users"),
		payload.get("user_limit"),
		payload.get("max_users"),
		payload.get("seats"),
		payload.get("seat_limit"),
		payload.get("quota_users"),
	]
	for candidate in candidates:
		parsed = _to_int_or_none(candidate)
		if parsed is not None:
			return parsed
	return None


def _extract_firelink_error(response):
	body = ""
	try:
		payload = response.json() if response.content else {}
	except Exception:
		payload = {}
	if isinstance(payload, dict):
		server_messages = payload.get("_server_messages")
		if isinstance(server_messages, str):
			try:
				parsed = json.loads(server_messages)
				if isinstance(parsed, list):
					messages = []
					for entry in parsed:
						if not isinstance(entry, str):
							continue
						try:
							entry_obj = json.loads(entry)
						except Exception:
							entry_obj = None
						if isinstance(entry_obj, dict):
							msg = str(entry_obj.get("message") or "").strip()
							if msg:
								messages.append(msg)
						elif entry.strip():
							messages.append(entry.strip())
					if messages:
						body = " | ".join(messages[:2])
			except Exception:
				body = server_messages.strip()
		if not body:
			msg = str(payload.get("message") or "").strip()
			if msg:
				body = msg
	if not body:
		try:
			body = str(response.text or "").strip()
		except Exception:
			body = ""
	body = " ".join(body.split())
	return body[:220]


def _build_firelink_endpoints():
	configured = str(frappe.db.get_default(FIRELINK_ENDPOINT_DEFAULT_KEY) or "").strip()
	if configured:
		return [configured] + [e for e in FIRELINK_ENDPOINT_CANDIDATES if e != configured]
	return FIRELINK_ENDPOINT_CANDIDATES


def _get_firelink_limit():
	if requests is None:
		raise Exception("requests is not available")

	base_url = (
		str(frappe.db.get_default(FIRELINK_BASE_DEFAULT_KEY) or FIRELINK_BASE_FALLBACK).strip()
		or FIRELINK_BASE_FALLBACK
	)
	base_headers = {"Accept": "application/json"}
	api_key = _get_membership_api_key()
	missing_key_note = ""
	if not api_key:
		membership_rows = (
			frappe.get_all(
				"FL Membership",
				fields=["name", "membership_status"],
				order_by="modified desc",
				limit_page_length=5,
			)
			if frappe.db.exists("DocType", "FL Membership")
			else []
		)
		if membership_rows:
			missing_key_note = (
				"No active FL Membership API key configured (membership_api_key is blank/unreadable)."
			)
		else:
			missing_key_note = (
				"No FL Membership record exists on this site to provide FireLink API credentials."
			)

	base_params = {"site": frappe.local.site, "host": frappe.local.site}
	auth_attempts = [({}, {})]
	if api_key:
		auth_attempts = [
			({"Authorization": f"Bearer {api_key}", "X-API-Key": api_key}, {}),
			({"Authorization": f"token {api_key}", "X-API-Key": api_key}, {}),
			({"Authorization": f"token {api_key}:{api_key}", "X-API-Key": api_key}, {}),
			({"X-API-Key": api_key, "X-FireLink-API-Key": api_key}, {"api_key": api_key}),
			({}, {"api_key": api_key, "token": api_key}),
			({}, {}),
		]

	reasons = []
	if missing_key_note:
		reasons.append(missing_key_note)
	for endpoint in _build_firelink_endpoints():
		url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
		for header_add, param_add in auth_attempts:
			headers = {**base_headers, **header_add}
			params = {**base_params, **param_add}
			try:
				response = requests.get(url, headers=headers, params=params, timeout=8, allow_redirects=True)
				if response.status_code >= 400:
					detail = _extract_firelink_error(response)
					reasons.append(f"{url} HTTP {response.status_code}" + (f" ({detail})" if detail else ""))
					continue
				data = response.json() if response.content else {}
				payload = (
					data.get("message")
					if isinstance(data, dict) and isinstance(data.get("message"), dict)
					else data
				)
				if not isinstance(payload, dict):
					reasons.append(f"{url} invalid JSON payload")
					continue
				limit = _extract_limit_from_payload(payload)
				if limit is None:
					reasons.append(f"{url} missing allowed_users/user_limit field")
					continue
				return limit, f"firelink:{url}"
			except Exception as exc:
				reasons.append(f"{url} {exc}")

	if reasons:
		tail = reasons[-3:]
		if missing_key_note and missing_key_note not in tail:
			tail = [missing_key_note] + tail[:2]
		reason = "; ".join(tail)
	else:
		reason = "no FireLink endpoints available"
	raise Exception(f"Live FireLink verification failed: {reason}")


def _resolve_allowed_user_limit(require_live=False):
	try:
		limit, source = _get_firelink_limit()
		_set_cached_limit(limit)
		return limit, source, True
	except Exception as exc:
		if require_live:
			raise
		firelink_error = str(exc).strip()

	local_limit, local_source = _get_local_membership_limit()
	if local_limit is not None:
		_set_cached_limit(local_limit)
		return local_limit, local_source, False

	default_limit, default_source = _get_default_limit()
	if default_limit is not None:
		_set_cached_limit(default_limit)
		return default_limit, default_source, False

	cached = _get_cached_limit()
	if cached is not None:
		return cached, f"site_default:{CACHED_LIMIT_DEFAULT_KEY}", False

	return None, "", False


@frappe.whitelist(allow_guest=False)
def get_user_roles():
	user = frappe.session.user
	full_name = frappe.db.get_value("User", user, "full_name") or user
	try:
		roles = frappe.get_roles(user) or []
	except Exception:
		rows = frappe.get_all(
			"Has Role",
			filters={"parenttype": "User", "parent": user},
			fields=["role"],
			limit=500,
		)
		roles = [r["role"] for r in rows]

	if user == "Administrator" and "System Manager" not in roles:
		roles.append("System Manager")
	roles.append("Authenticated")
	return {"user": user, "full_name": full_name, "roles": sorted(set(roles))}


@frappe.whitelist(allow_guest=False)
def get_user_seat_quota():
	verification_error = ""
	verified_live = False
	try:
		allowed_users, source, enforcement_enabled = _resolve_allowed_user_limit(require_live=True)
		verified_live = True
	except Exception as exc:
		verification_error = str(exc).strip()
		allowed_users, source, enforcement_enabled = _resolve_allowed_user_limit(require_live=False)
	used_users = _count_billable_enabled_users()
	remaining_users = None if allowed_users is None else max(0, allowed_users - used_users)
	return {
		"allowed_users": allowed_users,
		"used_users": used_users,
		"remaining_users": remaining_users,
		"enforcement_enabled": bool(enforcement_enabled and allowed_users is not None),
		"verified_live": verified_live,
		"verification_error": verification_error,
		"source": source,
	}


def enforce_user_seat_limit(doc, method=None):
	if getattr(frappe.flags, "in_install", False) or getattr(frappe.flags, "in_migrate", False):
		return
	if not getattr(doc, "enabled", 1):
		return
	name = str(getattr(doc, "name", "") or "").strip()
	if name in SYSTEM_EXCLUDED_USERS:
		return
	if _is_website_user(doc):
		return

	try:
		allowed_users, source, enforcement_enabled = _resolve_allowed_user_limit(require_live=True)
	except Exception as exc:
		frappe.throw(
			"Cannot verify user allowance with FireLink right now. "
			f"Blocking user creation/update until verification succeeds. Details: {exc}"
		)
		return
	if not enforcement_enabled or allowed_users is None:
		return

	used_without_target = _count_billable_enabled_users(exclude_user=name)
	if used_without_target >= allowed_users:
		remaining = max(0, allowed_users - used_without_target)
		source_note = f" Source: {source}." if source else ""
		frappe.throw(
			f"User limit reached ({used_without_target}/{allowed_users}). "
			f"No remaining seats ({remaining}) for new active system users.{source_note}"
		)
