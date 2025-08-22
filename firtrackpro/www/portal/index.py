import frappe
from frappe.utils import add_days, getdate, now_datetime

from firtrackpro.portal_utils import build_portal_context

no_cache = 1


def _safe_get_all(doctype, *, fields=None, filters=None, order_by=None, limit=5):
	"""Lightweight helper: return [] if the doctype/fields dont exist."""
	try:
		return frappe.get_all(
			doctype,
			fields=fields or ["name"],
			filters=filters or {},
			order_by=order_by,
			limit=limit,
		)
	except Exception:
		return []


def _safe_count(doctype, filters=None):
	try:
		return frappe.db.count(doctype, filters or {})
	except Exception:
		return 0


def get_context(context):
	# Common portal chrome (auth + user bits)
	build_portal_context(
		context,
		page_h1="Portal",
		messages_url="/portal/messages",
		notifications_url="/app/notifications",
		force_login=True,
	)

	# If we redirected to login, bail out early
	if frappe.local.response.get("type") == "redirect":
		return context

	user = frappe.session.user
	now = now_datetime()
	in_7_days = add_days(getdate(now), 7)

	# --- Data sources (best-effort; empty lists if unavailable) ---

	# 1) My open ToDos (Frappe core)
	todos = _safe_get_all(
		"ToDo",
		fields=["name", "status", "date", "description", "reference_type", "reference_name"],
		filters={"allocated_to": user, "status": ["!=", "Closed"]},
		order_by="date asc, creation asc",
		limit=5,
	)

	# 2) Recent messages (Communication) where Im a recipient
	messages = _safe_get_all(
		"Communication",
		fields=["name", "subject", "creation", "status"],
		filters={"communication_type": "Communication", "recipients": ["like", f"%{user}%"]},
		order_by="creation desc",
		limit=5,
	)

	# 3) Unread notification count (Notification Log)
	unread_notifications = _safe_count("Notification Log", {"for_user": user, "seen": 0})

	# 4) Upcoming events I own (simple personal calendar view)
	events = _safe_get_all(
		"Event",
		fields=["name", "subject", "starts_on"],
		filters={"owner": user, "starts_on": [">=", now], "ends_on": ["<=", in_7_days]},
		order_by="starts_on asc",
		limit=5,
	)
	# Some ERPs dont populate ends_on; fallback to just starts_on >= now
	if not events:
		events = _safe_get_all(
			"Event",
			fields=["name", "subject", "starts_on"],
			filters={"owner": user, "starts_on": [">=", now]},
			order_by="starts_on asc",
			limit=5,
		)

	# 5) Quick links (role-agnostic, your sidebar already RBACs navigation)
	quick_links = [
		{"icon": "fa-solid fa-calendar-days", "label": "Scheduler", "href": "/portal/scheduler"},
		{"icon": "fa-solid fa-list-check", "label": "Tasks", "href": "/portal/tasks"},
		{"icon": "fa-solid fa-map", "label": "Sites", "href": "/portal/sites"},
		{"icon": "fa-solid fa-box-archive", "label": "Assets", "href": "/portal/assets"},
		{"icon": "fa-solid fa-file-invoice-dollar", "label": "Invoices", "href": "/portal/invoices"},
		{"icon": "fa-solid fa-chart-column", "label": "Reports", "href": "/portal/reports"},
	]

	# Summaries
	context.todo_list = todos
	context.todo_count = len(todos)
	context.message_list = messages
	context.message_count = len(messages)
	context.unread_notifications = unread_notifications
	context.event_list = events
	context.event_count = len(events)
	context.quick_links = quick_links

	return build_portal_context(context, page_h1="Dashboard", force_login=True)
