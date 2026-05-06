import json
from urllib.parse import urlparse

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
FIRELINK_BRIDGE_TOKEN_KEYS = [
	"firelink_bridge_token",
	"firtrackpro_firelink_bridge_token",
]
FIRELINK_ENDPOINT_FALLBACK = "/api/method/firtrackpro.api.integrations.firelink_admin_subscriptions_bridge"
FIRELINK_ENDPOINT_CANDIDATES = [
	"/api/method/firtrackpro.api.integrations.firelink_admin_subscriptions_bridge",
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


def _as_str(value):
	if value is None:
		return ""
	return str(value).strip()


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
	if isinstance(payload.get("quota"), dict):
		quota = payload.get("quota") or {}
		candidates = [
			quota.get("allowed_users"),
			quota.get("allowed_users_total"),
			payload.get("allowed_users"),
		]
	else:
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


def _firelink_bridge_token():
	for key in FIRELINK_BRIDGE_TOKEN_KEYS:
		val = str(frappe.db.get_default(key) or "").strip()
		if val:
			return val
	return ""


def _normalize_host(raw):
	host = str(raw or "").strip().lower()
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


def _get_firelink_limit():
	if requests is None:
		raise Exception("requests is not available")

	base_url = (
		str(frappe.db.get_default(FIRELINK_BASE_DEFAULT_KEY) or FIRELINK_BASE_FALLBACK).strip()
		or FIRELINK_BASE_FALLBACK
	)
	base_headers = {"Accept": "application/json"}
	api_key = _get_membership_api_key()
	bridge_token = _firelink_bridge_token()
	missing_key_note = ""
	if not api_key and not bridge_token:
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
	site_host = _normalize_host(frappe.local.site)
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
				if endpoint.endswith("firelink_admin_subscriptions_bridge"):
					bridge_headers = {
						**headers,
						"Content-Type": "application/x-www-form-urlencoded",
					}
					if site_host:
						bridge_headers["Origin"] = f"https://{site_host}"
						bridge_headers["Referer"] = f"https://{site_host}/portal"
					response = None
					payload = None
					bridge_error = None
					for bridge_action in ("quota", "list"):
						form = {
							"action": bridge_action,
							"site_host": site_host,
							"host": site_host,
							"site": site_host,
						}
						if bridge_token:
							form["bridge_token"] = bridge_token
						response = requests.post(
							url,
							headers=bridge_headers,
							data=form,
							timeout=8,
							allow_redirects=True,
						)
						if response.status_code >= 400:
							bridge_error = _extract_firelink_error(response) or f"HTTP {response.status_code}"
							continue
						data = response.json() if response.content else {}
						payload = (
							data.get("message")
							if isinstance(data, dict) and isinstance(data.get("message"), dict)
							else data
						)
						if not isinstance(payload, dict):
							bridge_error = "invalid JSON payload"
							continue
						if bridge_action == "list":
							rows = payload.get("rows")
							if not isinstance(rows, list):
								bridge_error = "list response missing rows"
								continue
							targets = [site_host]
							if site_host.startswith("www."):
								targets.append(site_host[4:])
							match = None
							for row in rows:
								if not isinstance(row, dict):
									continue
								row_host = _normalize_host(row.get("site_host"))
								if row_host in targets:
									match = row
									break
							if not match:
								bridge_error = f"no FL Site Subscription for host {site_host}"
								continue
							payload = {
								"allowed_users": match.get("allowed_users_total"),
								"source": "FL Site Subscription.allowed_users_total",
							}
						bridge_error = None
						break
					if bridge_error:
						reasons.append(f"{url} {bridge_error}")
						continue
				else:
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
				if isinstance(payload.get("quota"), dict):
					quota = payload.get("quota") or {}
					if quota.get("found") is False:
						reasons.append(f"{url} no FL Site Subscription for host {site_host}")
						continue
				limit = _extract_limit_from_payload(payload)
				if limit is None:
					reasons.append(f"{url} missing allowed_users/user_limit field")
					continue
				if isinstance(payload.get("quota"), dict):
					source = str((payload.get("quota") or {}).get("source") or "").strip()
					if not source:
						source = "FL Site Subscription.allowed_users_total"
					return limit, f"firelink:{source}"
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


def _generate_temp_password(length=12):
	import secrets
	import string
	alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
	return "".join(secrets.choice(alphabet) for _ in range(max(8, int(length or 12))))


def _first_name_from_full_name(full_name):
	value = str(full_name or "").strip()
	if not value:
		return "Client"
	parts = value.split()
	return parts[0] if parts else "Client"


def _safe_set_if_field(doc, fieldname, value):
	try:
		meta = doc.meta if getattr(doc, "meta", None) else frappe.get_meta(doc.doctype)
		if meta and meta.has_field(fieldname):
			doc.set(fieldname, value)
	except Exception:
		pass


def _first_existing_field(doctype: str, candidates: list[str]) -> str:
	try:
		meta = frappe.get_meta(doctype)
	except Exception:
		return ""
	for fieldname in candidates:
		try:
			if meta.has_field(fieldname):
				return fieldname
		except Exception:
			continue
	return ""


def _ensure_contact_link_for_customer(customer: str, full_name: str, email: str, mobile_no: str = "") -> None:
	customer = _as_str(customer)
	email = _as_str(email).lower()
	if not customer or not email:
		return
	try:
		if not frappe.db.exists("Customer", customer):
			return
		existing_contacts = frappe.db.sql(
			"""
			select distinct dl.parent
			from `tabDynamic Link` dl
			join `tabContact Email` ce on ce.parent = dl.parent
			where dl.parenttype = 'Contact'
			  and dl.link_doctype = 'Customer'
			  and dl.link_name = %s
			  and lower(ce.email_id) = %s
			limit 1
			""",
			(customer, email),
			as_list=True,
		)
		if existing_contacts:
			return

		contact = frappe.new_doc("Contact")
		contact.first_name = _first_name_from_full_name(full_name) or "Client"
		contact.last_name = " ".join(_as_str(full_name).split()[1:]) or None
		if _as_str(mobile_no):
			contact.append("phone_nos", {"phone": _as_str(mobile_no), "is_primary_phone": 1})
		contact.append("email_ids", {"email_id": email, "is_primary": 1})
		contact.append("links", {"link_doctype": "Customer", "link_name": customer})
		contact.insert(ignore_permissions=True)
	except Exception:
		# Best-effort linkage only; provisioning must still succeed.
		pass


def _clean_whitelisted_kwargs(kwargs):
	data = dict(kwargs or {})
	for key in ("cmd", "method", "data"):
		data.pop(key, None)
	return data


@frappe.whitelist(allow_guest=False)
def provision_client_portal_login(login_name=None, customer=None, full_name=None, email=None, mobile_no=None, notes=None, enabled=1):
	has_login_doctype = bool(frappe.db.exists("DocType", "FT Client Portal Login"))

	customer = str(customer or "").strip()
	full_name = str(full_name or "").strip()
	email = str(email or "").strip().lower()
	mobile_no = str(mobile_no or "").strip()
	notes = str(notes or "").strip()
	enabled_int = 1 if str(enabled).strip().lower() not in ("0", "false", "no") else 0

	if not customer:
		frappe.throw("Customer is required.")
	if not full_name:
		frappe.throw("Full name is required.")
	if not email:
		frappe.throw("Email is required.")

	login_doc = None
	if has_login_doctype:
		key = str(login_name or "").strip()
		if key and frappe.db.exists("FT Client Portal Login", key):
			login_doc = frappe.get_doc("FT Client Portal Login", key)
		else:
			rows = frappe.get_all(
				"FT Client Portal Login",
				filters={"customer": customer, "email": email},
				fields=["name"],
				limit_page_length=1,
			)
			if rows:
				login_doc = frappe.get_doc("FT Client Portal Login", rows[0]["name"])

		if not login_doc:
			login_doc = frappe.new_doc("FT Client Portal Login")
			login_doc.customer = customer

		login_doc.customer = customer
		login_doc.full_name = full_name
		login_doc.email = email
		_safe_set_if_field(login_doc, "mobile_no", mobile_no or None)
		_safe_set_if_field(login_doc, "notes", notes or None)
		_safe_set_if_field(login_doc, "enabled", enabled_int)

		if login_doc.is_new():
			login_doc.insert(ignore_permissions=True)
		else:
			login_doc.save(ignore_permissions=True)

	user_name = email
	if frappe.db.exists("User", user_name):
		user_doc = frappe.get_doc("User", user_name)
	else:
		user_doc = frappe.new_doc("User")
		user_doc.email = user_name
		user_doc.username = user_name
		user_doc.send_welcome_email = 0
		user_doc.user_type = "Website User"

	user_doc.first_name = _first_name_from_full_name(full_name)
	user_doc.full_name = full_name
	user_doc.mobile_no = mobile_no or None
	user_doc.enabled = enabled_int
	user_doc.user_type = "Website User"
	user_doc.send_welcome_email = 0
	# Keep a direct customer->user link when tenant has a custom field on User.
	for customer_field in ("customer", "portal_customer", "client_customer", "ft_customer"):
		_safe_set_if_field(user_doc, customer_field, customer)
	if user_doc.is_new():
		user_doc.insert(ignore_permissions=True)
	else:
		user_doc.save(ignore_permissions=True)
	_ensure_contact_link_for_customer(customer, full_name, user_name, mobile_no)

	# Keep this user out of paid staff-seat counts by enforcing Website User type.
	temp_password = _generate_temp_password(12)
	try:
		from frappe.utils.password import update_password
		update_password(user_name, temp_password, logout_all_sessions=True)
	except Exception:
		frappe.throw("Unable to set temporary password for client user.")

	if login_doc:
		_safe_set_if_field(login_doc, "provisioned_at", frappe.utils.now_datetime())
		_safe_set_if_field(login_doc, "provisioned_user", user_name)
		_safe_set_if_field(login_doc, "requires_password_reset", 1)
		_safe_set_if_field(login_doc, "user", user_name)
		_safe_set_if_field(login_doc, "portal_user", user_name)
		login_doc.save(ignore_permissions=True)

	site = (frappe.utils.get_url() or "").rstrip("/")
	client_login_url = f"{site}/client/login"
	subject = "Your FireTrack Client Portal Access"
	message = (
		f"Hi {full_name},<br><br>"
		"Your client portal login is ready.<br><br>"
		f"Login URL: <a href=\"{client_login_url}\">{client_login_url}</a><br>"
		f"Username: {user_name}<br>"
		f"Temporary Password: {temp_password}<br><br>"
		"After first login, go to Account and change your password.<br><br>"
		"If you did not request this access, contact your FireTrack administrator."
	)
	email_sent = True
	email_error = ""
	try:
		frappe.sendmail(recipients=[user_name], subject=subject, message=message, delayed=False)
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), "Client Portal Invite Email Failed")
		email_sent = False
		email_error = _as_str(exc)

	return {
		"ok": True,
		"login_name": (login_doc.name if login_doc else user_name),
		"user": user_name,
		"email": user_name,
		"temporary_password_sent": email_sent,
		"email_sent": email_sent,
		"email_error": email_error or None,
		"login_url": client_login_url,
		"has_login_doctype": has_login_doctype,
		"message": "Client portal login provisioned and invite email sent." if email_sent else "Client portal login provisioned, but invite email failed.",
	}


@frappe.whitelist(allow_guest=False)
def provision_client_login(**kwargs):
	return provision_client_portal_login(**_clean_whitelisted_kwargs(kwargs))


@frappe.whitelist(allow_guest=False)
def list_client_portal_logins_by_customer(customer=None):
	customer = _as_str(customer)
	if not customer:
		return {"rows": []}

	# Primary source: explicit portal-login doctype (when installed on tenant).
	if frappe.db.exists("DocType", "FT Client Portal Login"):
		rows = frappe.get_all(
			"FT Client Portal Login",
			filters={"customer": customer},
			fields=[
				"name",
				"customer",
				"full_name",
				"email",
				"mobile_no",
				"enabled",
				"last_login_at",
				"provisioned_at",
				"provisioned_user",
				"requires_password_reset",
				"notes",
				"modified",
			],
			order_by="modified desc",
			limit_page_length=500,
		)
		return {"rows": rows or []}

	# Fallback source 1: Website User records linked to this customer via custom field.
	customer_field = _first_existing_field("User", ["customer", "portal_customer", "client_customer", "ft_customer"])
	user_rows = []
	if customer_field:
		user_rows = frappe.get_all(
			"User",
			filters={customer_field: customer, "user_type": "Website User"},
			fields=["name", "full_name", "email", "mobile_no", "enabled", "last_login", "modified"],
			order_by="modified desc",
			limit_page_length=500,
		)

	# Fallback source 2: Website users whose email is linked to contacts on this customer.
	if not user_rows:
		emails = set()
		try:
			customer_email = _as_str(frappe.db.get_value("Customer", customer, "email_id"))
			if customer_email:
				emails.add(customer_email.lower())
		except Exception:
			pass
		try:
			contact_emails = frappe.db.sql(
				"""
				select lower(ce.email_id)
				from `tabDynamic Link` dl
				join `tabContact Email` ce on ce.parent = dl.parent
				where dl.parenttype = 'Contact'
				  and dl.link_doctype = 'Customer'
				  and dl.link_name = %s
				  and ifnull(ce.email_id, '') != ''
				""",
				(customer,),
				as_list=True,
			)
			for row in contact_emails or []:
				value = _as_str((row or [None])[0]).lower()
				if value:
					emails.add(value)
		except Exception:
			pass

		if emails:
			user_rows = frappe.get_all(
				"User",
				filters={"user_type": "Website User", "email": ["in", sorted(emails)]},
				fields=["name", "full_name", "email", "mobile_no", "enabled", "last_login", "modified"],
				order_by="modified desc",
				limit_page_length=500,
			)
	rows = [
		{
			"name": _as_str(r.get("name")),
			"customer": customer,
			"full_name": _as_str(r.get("full_name")),
			"email": _as_str(r.get("email")),
			"mobile_no": _as_str(r.get("mobile_no")),
			"enabled": 1 if int(r.get("enabled") or 0) else 0,
			"last_login_at": r.get("last_login"),
			"provisioned_at": None,
			"provisioned_user": _as_str(r.get("name")),
			"requires_password_reset": 0,
			"notes": "",
			"modified": r.get("modified"),
		}
		for r in (user_rows or [])
	]
	return {"rows": rows}


@frappe.whitelist(allow_guest=False)
def provision_contractor_portal_login(login_name=None, supplier=None, full_name=None, email=None, mobile_no=None, notes=None, enabled=1):
	has_login_doctype = bool(frappe.db.exists("DocType", "FT Contractor Portal Login"))
	supplier = str(supplier or "").strip()
	full_name = str(full_name or "").strip()
	email = str(email or "").strip().lower()
	mobile_no = str(mobile_no or "").strip()
	notes = str(notes or "").strip()
	enabled_int = 1 if str(enabled).strip().lower() not in ("0", "false", "no") else 0
	if not supplier:
		frappe.throw("Supplier is required.")
	if not full_name:
		frappe.throw("Full name is required.")
	if not email:
		frappe.throw("Email is required.")
	login_doc = None
	if has_login_doctype:
		key = str(login_name or "").strip()
		if key and frappe.db.exists("FT Contractor Portal Login", key):
			login_doc = frappe.get_doc("FT Contractor Portal Login", key)
		else:
			rows = frappe.get_all("FT Contractor Portal Login", filters={"supplier": supplier, "email": email}, fields=["name"], limit_page_length=1)
			if rows:
				login_doc = frappe.get_doc("FT Contractor Portal Login", rows[0]["name"])
		if not login_doc:
			login_doc = frappe.new_doc("FT Contractor Portal Login")
		_safe_set_if_field(login_doc, "supplier", supplier)
		_safe_set_if_field(login_doc, "full_name", full_name)
		_safe_set_if_field(login_doc, "email", email)
		_safe_set_if_field(login_doc, "mobile_no", mobile_no or None)
		_safe_set_if_field(login_doc, "notes", notes or None)
		_safe_set_if_field(login_doc, "enabled", enabled_int)
		if login_doc.is_new():
			login_doc.insert(ignore_permissions=True)
		else:
			login_doc.save(ignore_permissions=True)
	user_name = email
	if frappe.db.exists("User", user_name):
		user_doc = frappe.get_doc("User", user_name)
	else:
		user_doc = frappe.new_doc("User")
		user_doc.email = user_name
		user_doc.username = user_name
		user_doc.send_welcome_email = 0
		user_doc.user_type = "Website User"
	user_doc.first_name = _first_name_from_full_name(full_name)
	user_doc.full_name = full_name
	user_doc.mobile_no = mobile_no or None
	user_doc.enabled = enabled_int
	user_doc.user_type = "Website User"
	user_doc.send_welcome_email = 0
	if user_doc.is_new():
		user_doc.insert(ignore_permissions=True)
	else:
		user_doc.save(ignore_permissions=True)
	temp_password = _generate_temp_password(12)
	from frappe.utils.password import update_password
	update_password(user_name, temp_password, logout_all_sessions=True)
	for role_name in ("Contractor Portal User", "Contractor"):
		if frappe.db.exists("Role", role_name) and not frappe.db.exists("Has Role", {"parent": user_name, "role": role_name}):
			try:
				user_doc.append("roles", {"role": role_name})
			except Exception:
				pass
	try:
		user_doc.save(ignore_permissions=True)
	except Exception:
		pass
	if login_doc:
		_safe_set_if_field(login_doc, "provisioned_at", frappe.utils.now_datetime())
		_safe_set_if_field(login_doc, "provisioned_user", user_name)
		_safe_set_if_field(login_doc, "requires_password_reset", 1)
		_safe_set_if_field(login_doc, "user", user_name)
		_safe_set_if_field(login_doc, "portal_user", user_name)
		login_doc.save(ignore_permissions=True)
	site = (frappe.utils.get_url() or "").rstrip("/")
	contractor_login_url = f"{site}/contractor/login"
	subject = "Your FireTrack Contractor Portal Access"
	message = (
		f"Hi {full_name},<br><br>"
		"Your contractor portal login is ready.<br><br>"
		f"Login URL: <a href=\"{contractor_login_url}\">{contractor_login_url}</a><br>"
		f"Username: {user_name}<br>"
		f"Temporary Password: {temp_password}<br><br>"
		"After first login, go to Account and change your password."
	)
	email_sent = True
	email_error = ""
	try:
		frappe.sendmail(recipients=[user_name], subject=subject, message=message, delayed=False)
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), "Contractor Portal Invite Email Failed")
		email_sent = False
		email_error = _as_str(exc)
	return {
		"ok": True,
		"login_name": (login_doc.name if login_doc else user_name),
		"user": user_name,
		"email": user_name,
		"temporary_password_sent": email_sent,
		"email_sent": email_sent,
		"email_error": email_error or None,
		"login_url": contractor_login_url,
		"has_login_doctype": has_login_doctype,
		"message": "Contractor portal login provisioned and invite email sent." if email_sent else "Contractor portal login provisioned, but invite email failed.",
	}


@frappe.whitelist(allow_guest=False)
def provision_contractor_login(**kwargs):
	return provision_contractor_portal_login(**_clean_whitelisted_kwargs(kwargs))
