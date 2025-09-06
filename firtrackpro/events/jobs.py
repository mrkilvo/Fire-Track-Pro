# apps/firtrackpro/firtrackpro/events/jobs.py
import frappe
from frappe.realtime import publish_realtime, get_site_room

def _emit(event: str, docname: str, doc=None):
    payload = {"doctype": "FT Job", "name": docname}
    if doc:
        # Add a few useful hints for the mobile list to optionally use
        for src, dest in [
            ("job_status", "job_status"),
            ("scheduled", "scheduled"),
            ("job_scheduled_start", "scheduled"),
            ("property", "property"),
            ("job_property", "property"),
            ("subject", "subject"),
            ("job_title", "subject"),
        ]:
            val = getattr(doc, src, None)
            if val and dest not in payload:
                payload[dest] = val

    # Broadcast to everyone connected on this site
    publish_realtime(event, payload, room=get_site_room(), after_commit=True)

def emit_job_inserted(doc, method=None):
    _emit("ft_job_inserted", doc.name, doc)

def emit_job_updated(doc, method=None):
    _emit("ft_job_updated", doc.name, doc)

def emit_job_deleted(doc, method=None):
    _emit("ft_job_deleted", doc.name)
