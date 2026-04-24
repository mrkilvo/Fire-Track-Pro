# firtrackpro/ft_job/realtime.py
import frappe


def on_after_insert(doc, method=None):
	payload = {
		"name": doc.name,
		"job_title": doc.get("job_title"),
		"job_property": doc.get("job_property"),
		"job_status": doc.get("job_status"),
		"modified": doc.modified,
	}
	frappe.publish_realtime(
		event="ft_job:new", message=payload, doctype="FT Job", docname=doc.name, after_commit=True
	)
