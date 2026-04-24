# apps/firtrackpro/firtrackpro/ft_job_events.py
import frappe


def _site_room() -> str:
	# mobile subscribes to both "site" and "site:<host>"
	return f"site:{frappe.local.site}"


def _emit(evt: str, docname: str, extra: dict | None = None):
	"""
	Publish to rooms your app already listens to:
	  - doctype:FT Job
	  - site:<host>
	  - all   (harmless extra fanout)
	Use after_commit=True to ensure clients refresh AFTER the DB write is committed.
	"""
	payload = {"doctype": "FT Job", "name": docname}
	if extra:
		payload.update(extra)

	# doctype room (primary)
	frappe.publish_realtime(evt, payload, room="doctype:FT Job", after_commit=True)
	# site-scoped + global room (secondary; okay to keep for visibility)
	frappe.publish_realtime(evt, payload, room=_site_room(), after_commit=True)
	frappe.publish_realtime(evt, payload, room="all", after_commit=True)


def after_insert(doc, method=None):
	# New document saved
	_emit("ft_job:new", doc.name)
	_emit("ft_job_updated", doc.name)


def on_update(doc, method=None):
	# Any save (status changes, fields, etc.)
	_emit("ft_job:update", doc.name)
	_emit("ft_job_updated", doc.name)


def on_trash(doc, method=None):
	# Before delete finalizes, name still available
	_emit("ft_job:deleted", doc.name)
	_emit("ft_job_updated", doc.name)


# Optional: bump list when schedules change
def schedule_bump(doc, method=None):
	frappe.publish_realtime(
		"ft_schedule_updated",
		{"doctype": "FT Schedule", "name": doc.name},
		room="doctype:FT Schedule",
		after_commit=True,
	)
	frappe.publish_realtime(
		"ft_schedule_updated", {"doctype": "FT Schedule"}, room=_site_room(), after_commit=True
	)
	frappe.publish_realtime("ft_schedule_updated", {"doctype": "FT Schedule"}, room="all", after_commit=True)
