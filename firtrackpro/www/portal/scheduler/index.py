# apps/firtrackpro/firtrackpro/www/portal/scheduler/index.py
import frappe
from datetime import date, timedelta
from firtrackpro.portal_utils import build_portal_context

no_cache = 1

def _demo_resources():
    # Add more techs so you can test vertical scrolling & filtering
    base = [
        {"id":"tech-alex","title":"Alex Lee","region":"CBD","skills":"Pumps, Panels"},
        {"id":"tech-ava","title":"Ava Singh","region":"CBD","skills":"Sprinklers, Hydrants"},
        {"id":"tech-liam","title":"Liam Brown","region":"North","skills":"Panels, Fault Find"},
        {"id":"tech-sam","title":"Sam Taylor","region":"North","skills":"Sprinklers, Hydrants"},
        {"id":"tech-jordan","title":"Jordan Patel","region":"South","skills":"Emergency Lighting"},
        {"id":"tech-zoe","title":"Zoe Chen","region":"South","skills":"Pumps"},
        {"id":"tech-casey","title":"Casey Nguyen","region":"West","skills":"Fault Finding"},
        {"id":"tech-max","title":"Max Wilson","region":"West","skills":"Sprinklers"},
    ]
    return base

def _demo_events():
    sites = ["ACME HQ","Harbour Tower","East Mall","Airport T3","Riverside Park"]
    times = ["08:00","09:00","10:00","12:00","14:00"]
    statuses = ["Open","In Progress","Completed"]
    techs = [r["id"] for r in _demo_resources()]
    today = date.today()
    out = []
    for i in range(48):
        d = (today + timedelta(days=i % 14)).strftime("%Y-%m-%d")
        out.append({
            "id": f"JOB-{1200+i}",
            "title": f"Service @ {sites[i % len(sites)]}",
            "start": f"{d}T{times[i % len(times)]}:00",
            "end":   f"{d}T{times[(i+1) % len(times)]}:00",
            "resourceId": techs[i % len(techs)],
            "extendedProps": {
                "status": statuses[i % len(statuses)],
                "site": sites[(i*3) % len(sites)]
            }
        })
    return out

def _demo_backlog():
    return [
        {"title":"Quarterly Service – Airport T3", "site":"Airport T3", "status":"Open"},
        {"title":"Panel Fault – East Mall", "site":"East Mall", "status":"In Progress"},
        {"title":"Hydrant Test – Riverside", "site":"Riverside Park", "status":"Open"},
        {"title":"Lighting Audit – Harbour Tower", "site":"Harbour Tower", "status":"Completed"},
    ]

def get_context(context):
    # Optional license key from site_config / Single doctype
    lic = getattr(frappe.conf, "fullcalendar_license_key", None)
    if not lic:
        try:
            lic = frappe.db.get_single_value("FT Settings", "fullcalendar_license_key")
        except Exception:
            lic = None

    context.FC_LICENSE_KEY   = lic or "GPL-My-Project-Is-Open-Source"
    context.PAGE_TITLE       = "Scheduler"
    context.actions          = ['export']
    context.RESOURCES        = _demo_resources()
    context.EVENTS           = _demo_events()
    context.BACKLOG          = _demo_backlog()
    context.STATUS_OPTIONS   = ["Open","In Progress","Completed","Cancelled"]

    return build_portal_context(context, page_h1="Scheduler", force_login=True)
