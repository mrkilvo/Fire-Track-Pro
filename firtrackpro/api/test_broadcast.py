# apps/firtrackpro/firtrackpro/api/test_broadcast.py
import frappe


@frappe.whitelist()
def ping_all(event="rt_probe", msg="hello"):
	"""
	Emit an event to the 'all' room (System Users).
	"""
	payload = {"ok": True, "msg": msg}
	frappe.publish_realtime(event, payload, room="all", after_commit=True)
	return {"ok": True, "event": event, "payload": payload, "sent_to": ["all"]}


@frappe.whitelist()
def ping_doctype(doctype="FT Job", name=None, event="ft_job_updated"):
	"""
	Emit to the DocType room, so anyone subscribed to that doctype receives it.
	Also optionally include the docname in the payload for the client.
	"""
	payload = {"doctype": doctype, "name": name, "msg": f"ping_doctype:{doctype}"}
	frappe.publish_realtime(event, payload, doctype=doctype, after_commit=True)
	return {"ok": True, "event": event, "payload": payload, "sent_to": [f"doctype:{doctype}"]}


@frappe.whitelist()
def ping_job_update_event(name="TEST"):
	"""
	Convenience to mimic a job change signal without writing the DB.
	Emits the same event your app listens to.
	"""
	event = "ft_job_updated"
	payload = {"doctype": "FT Job", "name": name, "msg": "simulated update"}
	# Broadcast to all FT Job listeners
	frappe.publish_realtime(event, payload, doctype="FT Job", after_commit=True)
	# Optionally, also to the specific document channel:
	frappe.publish_realtime(event, payload, doctype="FT Job", docname=name, after_commit=True)
	return {
		"ok": True,
		"event": event,
		"payload": payload,
		"sent_to": ["doctype:FT Job", f"doc:FT Job/{name}"],
	}
