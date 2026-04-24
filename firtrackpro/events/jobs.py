# apps/firtrackpro/firtrackpro/events/jobs.py
import frappe


def _emit(event, payload, doctype=None, docname=None):
	if doctype:
		frappe.publish_realtime(event, payload, doctype=doctype, after_commit=True)
	if doctype and docname:
		frappe.publish_realtime(event, payload, doctype=doctype, docname=docname, after_commit=True)

	# Fallback broadcast path (mobile subscribes to "all")
	frappe.publish_realtime(event, payload, room="all", after_commit=True)


def emit_job_inserted(doc, _event):
	payload = {"doctype": "FT Job", "name": doc.name, "action": "inserted"}
	_emit("ft_job:new", payload, doctype="FT Job", docname=doc.name)
	_emit("ft_job_updated", payload, doctype="FT Job")


def emit_job_updated(doc, _event):
	payload = {"doctype": "FT Job", "name": doc.name, "action": "updated"}
	_emit("ft_job:update", payload, doctype="FT Job", docname=doc.name)
	_emit("ft_job_updated", payload, doctype="FT Job")


def emit_job_deleted(doc, _event):
	payload = {"doctype": "FT Job", "name": doc.name, "action": "deleted"}
	_emit("ft_job:deleted", payload, doctype="FT Job")
	_emit("ft_job_updated", payload, doctype="FT Job")


def emit_schedule_inserted(doc, _event):
	payload = {"doctype": "FT Schedule", "name": doc.name, "action": "inserted"}
	_emit("ft_schedule_updated", payload, doctype="FT Schedule")


def emit_schedule_updated(doc, _event):
	payload = {"doctype": "FT Schedule", "name": doc.name, "action": "updated"}
	_emit("ft_schedule_updated", payload, doctype="FT Schedule")
