# apps/firtrackpro/firtrackpro/api/test_broadcast.py
from __future__ import annotations

import json
from typing import Optional
import frappe


def _site_host() -> str:
    # Prefer host seen on the request (DNS multitenant); fallback to site name
    host = (getattr(frappe.local, "request", None) and frappe.local.request.host) or None
    return host or frappe.local.site


def _ok(**kw):
    return {"ok": True, **kw}


# ---------------------------------------------------------------------------
# PUBLISH (normal path) – publish_realtime with after_commit=False
# ---------------------------------------------------------------------------

@frappe.whitelist(allow_guest=True)
def ping_all(event: str = "rt_probe", msg: str = "hello from ping_all"):
    """Broadcast to EVERYONE connected (no room)."""
    payload = {"msg": msg, "from": "test_broadcast"}
    frappe.publish_realtime(event=event, message=payload, after_commit=False)
    return _ok(scope="all", event=event, payload=payload)


@frappe.whitelist(allow_guest=True)
def ping_site(event: str = "rt_probe", msg: str = "hello from ping_site"):
    """Broadcast to site room: site:<host>."""
    host = _site_host()
    room = f"site:{host}"
    payload = {"msg": msg, "from": "test_broadcast"}
    frappe.publish_realtime(event=event, message=payload, room=room, after_commit=False)
    return _ok(scope="site", site=host, room=room, event=event, payload=payload)


@frappe.whitelist(allow_guest=True)
def ping_doctype(doctype: str, event: str = "rt_probe",
                 name: Optional[str] = None, msg: Optional[str] = None):
    """Broadcast to doctype room: doctype:<doctype>."""
    room = f"doctype:{doctype}"
    payload = {"msg": msg or f"hello from ping_doctype ({doctype})", "doctype": doctype, "name": name}
    frappe.publish_realtime(event=event, message=payload, room=room, after_commit=False)
    return _ok(scope="doctype", room=room, event=event, payload=payload)


@frappe.whitelist()
def ping_user(user: str, event: str = "rt_probe", msg: str = "hello from ping_user"):
    """Broadcast to user room: user:<email>. Requires auth (no allow_guest)."""
    room = f"user:{user}"
    payload = {"msg": msg, "to": user, "from": "test_broadcast"}
    frappe.publish_realtime(event=event, message=payload, room=room, after_commit=False)
    return _ok(scope="user", room=room, event=event, payload=payload)


@frappe.whitelist(allow_guest=True)
def echo(event: str = "rt_probe", msg: str = "echo"):
    """Send to everyone AND the current site room."""
    host = _site_host()
    payload = {"msg": msg, "site": host, "from": "echo"}
    frappe.publish_realtime(event=event, message=payload, after_commit=False)
    frappe.publish_realtime(event=event, message=payload, room=f"site:{host}", after_commit=False)
    return _ok(scope="both", event=event, payload=payload)


# ---------------------------------------------------------------------------
# DEBUG / DIAGNOSTICS – show redis + key; push directly to events list
# ---------------------------------------------------------------------------

@frappe.whitelist(allow_guest=True)
def debug_info():
    """Reveal the redis_socketio URL, events key, llen, and a ping."""
    from frappe.realtime import get_redis_key
    info = {
        "site": frappe.local.site,
        "user": frappe.session.user,
        "redis_socketio": frappe.local.conf.get("redis_socketio"),
        "events_key": get_redis_key("events"),
    }
    try:
        r = frappe.redis_socketio  # RedisWrapper pointing at redis_socketio
        info["redis_ping"] = bool(r.ping())
        info["llen_events"] = int(r.llen(get_redis_key("events")))
    except Exception as e:
        info["redis_error"] = str(e)
    return info


@frappe.whitelist(allow_guest=True)
def debug_push(event: str = "rt_probe", msg: str = "hello from debug_push",
               room: Optional[str] = None, user: Optional[str] = None,
               doctype: Optional[str] = None, docname: Optional[str] = None):
    """
    Direct RPUSH to the Socket.IO events list in the exact JSON shape
    that frappe.publish_realtime would write. This bypasses any transaction gating.
    """
    from frappe.realtime import get_redis_key
    r = frappe.redis_socketio
    key = get_redis_key("events")

    ev = {
        "event": event,
        "message": {"msg": msg, "from": "debug_push"},
        "room": room,
        "user": user,
        "doctype": doctype,
        "docname": docname,
        "site": frappe.local.site,
    }
    before = int(r.llen(key))
    r.rpush(key, json.dumps(ev))
    after = int(r.llen(key))
    return {"ok": True, "key": key, "before": before, "after": after, "pushed": ev}
