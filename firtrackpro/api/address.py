import hashlib
import json

import frappe
from frappe.integrations.utils import make_get_request
from frappe.utils import get_url


@frappe.whitelist(methods=["GET"], allow_guest=True)
def search(q=None, limit=7, country="AU"):
    q = (q or "").strip()
    if not q:
        return []
    try:
        limit = max(1, min(10, int(limit or 7)))
    except Exception:
        limit = 7
    country = (country or "AU").lower()
    params = {
        "format": "jsonv2",
        "addressdetails": 1,
        "q": q,
        "limit": limit,
        "countrycodes": country,
    }
    cache_key = (
        "addr:nominatim:"
        + hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()
    )
    cached = frappe.cache().get_value(cache_key)
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass
    headers = {
        "User-Agent": f"FireTrackPro/1.0 ({get_url()})",
        "Accept-Language": "en-AU",
    }
    try:
        res = make_get_request(
            "https://nominatim.openstreetmap.org/search", headers=headers, params=params
        )
    except Exception:
        try:
            import requests

            r = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params=params,
                headers=headers,
                timeout=10,
            )
            r.raise_for_status()
            res = r.json() if r.content else []
        except Exception:
            return []
    out = []
    if isinstance(res, list):
        for it in res:
            a = it.get("address") or {}
            line1 = (
                " ".join([p for p in [a.get("house_number"), a.get("road")] if p])
                or it.get("name")
                or it.get("display_name")
                or ""
            )
            suburb = (
                a.get("suburb")
                or a.get("city_district")
                or a.get("city")
                or a.get("town")
                or a.get("village")
                or ""
            )
            state = a.get("state") or ""
            postcode = a.get("postcode") or ""
            country_full = a.get("country") or "Australia"
            lat = it.get("lat")
            lon = it.get("lon")
            try:
                lat = round(float(lat), 6) if lat is not None else None
                lon = round(float(lon), 6) if lon is not None else None
            except Exception:
                lat = None
                lon = None
            out.append(
                {
                    "line1": line1,
                    "suburb": suburb,
                    "state": state,
                    "postcode": postcode,
                    "country": country_full,
                    "lat": lat,
                    "lng": lon,
                }
            )
    frappe.cache().set_value(cache_key, json.dumps(out), expires_in_sec=300)
    return out
