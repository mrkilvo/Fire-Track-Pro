# apps/firtrackpro/firtrackpro/portal/address_api.py
import frappe
from frappe import _
import requests

# Identify your app to Nominatim per usage policy
USER_AGENT = "FireTrackPro/1.0 (+https://firetrackpro.com.au; admin@firetrackpro.com.au)"

def _fmt_line1(addr: dict) -> str | None:
    """
    Compose a reasonable address_line1 from Nominatim parts.
    Prefer "house_number road", fall back to road/suburb/neighbourhood.
    """
    if not addr:
        return None
    house = addr.get("house_number")
    road = addr.get("road") or addr.get("pedestrian") or addr.get("footway")
    if house and road:
        return f"{house} {road}"
    return road or addr.get("neighbourhood") or addr.get("suburb") or addr.get("hamlet") or None


@frappe.whitelist()
def search_address(q: str, limit: int = 5, countrycodes: str = "au"):
    """
    Free address lookup via OpenStreetMap Nominatim.
    We proxy from server to set a proper User-Agent and keep things cacheable.
    """
    if frappe.session.user == "Guest":
        frappe.throw(_("Login required"), frappe.PermissionError)

    q = (q or "").strip()
    if len(q) < 3:
        return []

    # cache 1h by (country,query,limit)
    cache_key = f"ft_addrsearch::{countrycodes.lower()}::{q.lower()}::{int(limit)}"
    cached = frappe.cache().get_value(cache_key)
    if cached:
        return frappe.parse_json(cached)

    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": q,
        "format": "json",
        "addressdetails": 1,
        "limit": int(limit),
        "countrycodes": (countrycodes or "au"),
        "accept-language": "en-AU",
    }
    headers = {"User-Agent": USER_AGENT}

    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        raw = r.json()
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "FT Address Search failed")
        frappe.throw(_("Address search failed"), exc=e)

    results = []
    for it in raw or []:
        ad = it.get("address") or {}
        label = it.get("display_name")
        results.append({
            "label": label,
            "lat": it.get("lat"),
            "lng": it.get("lon"),
            "address_line1": _fmt_line1(ad),
            "address_line2": None,
            "city": ad.get("city") or ad.get("town") or ad.get("village") or ad.get("suburb") or ad.get("locality"),
            "state": ad.get("state"),
            "pincode": ad.get("postcode"),
            "country": ad.get("country"),
            "raw": ad,  # keep for debugging if you need it later
        })

    frappe.cache().set_value(cache_key, frappe.as_json(results), expires_in_sec=3600)
    return results
