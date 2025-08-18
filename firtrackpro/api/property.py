import json
import re
from datetime import datetime

import frappe
from frappe import _
from frappe.utils import add_months, get_datetime


def _slug_code(s: str) -> str:
	s = (s or "").strip()
	s = s.lower()
	s = re.sub(r"[^a-z0-9]+", "_", s)
	return s.strip("_") or "type"


def _title_label(s: str) -> str:
	s = (s or "").strip()
	return s[:1].upper() + s[1:] if s else s


def _ensure_asset_type(label_or_code: str) -> str:
	"""
	Resolve an FT Asset Type by name/label/code (case-insensitive).
	Create it if missing. Return the DocType *name* to use in Link fields.
	"""
	val = (label_or_code or "").strip()
	if not val:
		frappe.throw(_("asset_type is required"))

	# 1) Try exact name
	hit = frappe.get_all("FT Asset Type", filters={"name": val}, fields=["name"], limit=1)
	if hit:
		return hit[0]["name"]

	# 2) Try by label (case-insensitive)
	hit = frappe.get_all(
		"FT Asset Type",
		filters={"asset_type_label": ("like", val)},
		fields=["name"],
		limit=1,
	)
	if hit:
		return hit[0]["name"]

	# 3) Try by code (case-insensitive)
	hit = frappe.get_all(
		"FT Asset Type",
		filters={"asset_type_code": ("like", val.lower())},
		fields=["name"],
		limit=1,
	)
	if hit:
		return hit[0]["name"]

	# 4) Create a new one
	code = _slug_code(val)
	label = _title_label(val)
	doc = frappe.get_doc(
		{
			"doctype": "FT Asset Type",
			"asset_type_code": code,
			"asset_type_label": label,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _norm_asset_status(v: str) -> str:
	s = (v or "").strip().lower()
	if s in {"active", "inactive", "decommissioned"}:
		pass
	elif s in {"decommission", "decomm", "retired", "retire"}:
		s = "decommissioned"
	elif s in {"act", "on", "enabled"}:
		s = "active"
	elif s in {"off", "disable", "disabled"}:
		s = "inactive"
	else:
		s = "active"
	# return Title-case consistently
	return {
		"active": "Active",
		"inactive": "Inactive",
		"decommissioned": "Decommissioned",
	}[s]


def _payload():
	data = {}
	try:
		raw = getattr(frappe.request, "data", None)
		if raw:
			j = frappe.parse_json(raw)
			if isinstance(j, dict):
				data.update(j)
	except Exception:
		pass
	try:
		if frappe.form_dict:
			data.update(frappe.form_dict)
	except Exception:
		pass
	return data


def _has_field(doctype: str, fieldname: str) -> bool:
	try:
		meta = frappe.get_meta(doctype)
		return bool(meta.get_field(fieldname))
	except Exception:
		return False


def _ensure_customer(customer_name: str) -> str:
	if not (customer_name or "").strip():
		frappe.throw(_("Customer name required"))
	existing = frappe.get_all("Customer", filters={"customer_name": customer_name}, fields=["name"], limit=1)
	if existing:
		return existing[0]["name"]
	doc = frappe.get_doc({"doctype": "Customer", "customer_name": customer_name})
	doc.insert(ignore_permissions=True)
	return doc.name


def _create_address_from_display(
	title: str, display: str, customer_name: str | None, lat=None, lng=None
) -> str:
	ad_data = {
		"doctype": "Address",
		"address_title": (title or "Site")[:140],
		"address_line1": display or "",
		"country": "Australia",
	}
	if lat and _has_field("Address", "latitude"):
		ad_data["latitude"] = float(lat)
	if lng and _has_field("Address", "longitude"):
		ad_data["longitude"] = float(lng)
	ad = frappe.get_doc(ad_data)
	if customer_name:
		ad.append("links", {"link_doctype": "Customer", "link_name": customer_name})
	ad.insert(ignore_permissions=True)
	return ad.name


def _fmt_addr_text(a: dict) -> str:
	parts = [
		a.get("address_line1"),
		a.get("address_line2"),
		a.get("city"),
		a.get("state"),
		a.get("pincode"),
		a.get("country"),
	]
	parts = [p for p in parts if p]
	return ", ".join(parts)


@frappe.whitelist(methods=["POST"])
def create(
	property_name=None,
	customer_name=None,
	address_display=None,
	address_json=None,
	lat=None,
	lng=None,
):
	data = _payload()
	property_name = (data.get("property_name") or property_name or "").strip()
	customer_name = (data.get("customer_name") or customer_name or "").strip()
	address_display = data.get("address_display") or address_display or ""
	address_json = data.get("address_json") or address_json or ""
	lat = data.get("lat") or lat
	lng = data.get("lng") or lng

	if not property_name:
		frappe.throw(_("Property Display Name required"))

	cust_docname = _ensure_customer(customer_name) if customer_name else None

	# Address
	addr_docname = None
	if address_json:
		try:
			addr_obj = json.loads(address_json)
		except Exception:
			addr_obj = None
		if isinstance(addr_obj, dict):
			a = addr_obj.get("address") or {}
			line1 = (
				" ".join([x for x in [a.get("house_number"), a.get("road")] if x])
				or addr_obj.get("line1")
				or addr_obj.get("display_name")
				or address_display
			)
			suburb = (
				a.get("suburb")
				or a.get("city")
				or a.get("town")
				or a.get("village")
				or addr_obj.get("suburb")
				or ""
			)
			state = a.get("state") or addr_obj.get("state") or ""
			pincode = a.get("postcode") or addr_obj.get("postcode") or ""
			country = a.get("country") or addr_obj.get("country") or "Australia"
			ad_data = {
				"doctype": "Address",
				"address_title": property_name[:140],
				"address_line1": line1 or (address_display or ""),
				"address_line2": "",
				"city": suburb,
				"state": state,
				"pincode": pincode,
				"country": country,
			}
			if addr_obj.get("lat") and _has_field("Address", "latitude"):
				ad_data["latitude"] = addr_obj.get("lat")
			if addr_obj.get("lng") and _has_field("Address", "longitude"):
				ad_data["longitude"] = addr_obj.get("lng")
			ad = frappe.get_doc(ad_data)
			if cust_docname:
				ad.append("links", {"link_doctype": "Customer", "link_name": cust_docname})
			ad.insert(ignore_permissions=True)
			addr_docname = ad.name

	if not addr_docname and address_display:
		addr_docname = _create_address_from_display(property_name, address_display, cust_docname, lat, lng)

	# Create Property
	prop = frappe.get_doc(
		{
			"doctype": "FT Property",
			"property_name": property_name,
			"property_customer": cust_docname,
			"property_address": addr_docname,
			"property_lat": float(lat) if lat else None,
			"property_lng": float(lng) if lng else None,
			"property_notes": "",
		}
	)
	prop.insert(ignore_permissions=True)

	# Response
	addr_text = ""
	region = ""
	if addr_docname:
		a = frappe.get_all(
			"Address",
			filters={"name": addr_docname},
			fields=[
				"address_line1",
				"address_line2",
				"city",
				"state",
				"pincode",
				"country",
			],
			limit=1,
		)
		if a:
			addr_text = _fmt_addr_text(a[0])
			region = a[0].get("state") or ""
	return {
		"name": prop.name,
		"property_name": property_name,
		"client_name": customer_name or "",
		"address": addr_text,
		"status": "Active",
		"next_service": "—",
		"open_defects": 0,
		"region": region,
	}


@frappe.whitelist(methods=["POST"])
def set_client(property_name: str | None = None, customer_name: str | None = None):
	data = _payload()
	property_name = data.get("property_name") or property_name
	customer_name = data.get("customer_name") or customer_name
	if not property_name or not customer_name:
		frappe.throw(_("property_name and customer_name are required"))
	prop = frappe.get_doc("FT Property", property_name)
	cust = _ensure_customer(customer_name)
	prop.property_customer = cust
	prop.save(ignore_permissions=True)
	frappe.db.commit()
	return {"ok": True, "property": prop.name, "customer": cust}


@frappe.whitelist(methods=["POST"])
def save_notes(property_name: str | None = None, notes: str = ""):
	data = _payload()
	property_name = data.get("property_name") or property_name
	notes = data.get("notes") if data.get("notes") is not None else notes
	if not property_name:
		frappe.throw(_("property_name is required"))
	prop = frappe.get_doc("FT Property", property_name)
	prop.property_notes = notes or ""
	prop.save(ignore_permissions=True)
	frappe.db.commit()
	return {"ok": True}


@frappe.whitelist(methods=["POST"])
def save_address(
	property_name: str | None = None,
	line1: str = "",
	line2: str = "",
	suburb: str = "",
	state: str = "",
	postcode: str = "",
	country: str = "Australia",
	lat: str | None = None,
	lng: str | None = None,
):
	data = _payload()
	property_name = data.get("property_name") or property_name
	line1 = data.get("line1", line1)
	line2 = data.get("line2", line2)
	suburb = data.get("suburb", suburb)
	state = data.get("state", state)
	postcode = data.get("postcode", postcode)
	country = data.get("country", country) or "Australia"
	lat = data.get("lat", lat)
	lng = data.get("lng", lng)

	if not property_name:
		frappe.throw(_("property_name is required"))

	prop = frappe.get_doc("FT Property", property_name)
	ad_name = prop.property_address
	if ad_name:
		ad = frappe.get_doc("Address", ad_name)
	else:
		ad = frappe.new_doc("Address")

	update_map = {
		"address_title": (prop.property_name or "Site")[:140],
		"address_line1": line1 or "",
		"address_line2": line2 or "",
		"city": suburb or "",
		"state": state or "",
		"pincode": postcode or "",
		"country": country or "Australia",
	}
	if lat and _has_field("Address", "latitude"):
		update_map["latitude"] = float(lat)
	if lng and _has_field("Address", "longitude"):
		update_map["longitude"] = float(lng)

	ad.update(update_map)
	if prop.property_customer and not any(
		l.link_doctype == "Customer" and l.link_name == prop.property_customer for l in (ad.links or [])
	):
		ad.append("links", {"link_doctype": "Customer", "link_name": prop.property_customer})
	if ad.is_new():
		ad.insert(ignore_permissions=True)
	else:
		ad.save(ignore_permissions=True)

	prop.property_address = ad.name
	if lat:
		prop.property_lat = float(lat)
	if lng:
		prop.property_lng = float(lng)
	prop.save(ignore_permissions=True)
	frappe.db.commit()
	return {"ok": True, "address": ad.name}


@frappe.whitelist(methods=["POST"])
def upsert_access(
	property_name: str | None = None,
	alarm_panel: str = "",
	parking: str = "",
	keysafe_code: str | None = None,
	gate_code: str | None = None,
):
	data = _payload()
	property_name = data.get("property_name") or property_name
	alarm_panel = data.get("alarm_panel", alarm_panel) or ""
	parking = data.get("parking", parking) or ""
	keysafe_code = data.get("keysafe_code") if data.get("keysafe_code") is not None else keysafe_code
	gate_code = data.get("gate_code") if data.get("gate_code") is not None else gate_code

	if not property_name:
		frappe.throw(_("property_name is required"))

	prop = frappe.get_doc("FT Property", property_name)
	access_docname = getattr(prop, "property_access", None)
	if access_docname:
		acc = frappe.get_doc("FT Property Access", access_docname)
	else:
		acc = frappe.new_doc("FT Property Access")
		acc.property_access_property = prop.name

	if keysafe_code is not None:
		acc.property_access_keysafe_code = keysafe_code
	if gate_code is not None:
		acc.property_access_gate_code = gate_code
	acc.property_access_alarm_panel = alarm_panel
	acc.property_access_parking = parking

	if acc.is_new():
		acc.insert(ignore_permissions=True)
	else:
		acc.save(ignore_permissions=True)

	if not access_docname:
		prop.property_access = acc.name
		prop.save(ignore_permissions=True)

	frappe.db.commit()
	return {"ok": True, "access": acc.name}


@frappe.whitelist(methods=["POST"])
def add_contact(
	property_name: str | None = None,
	first_name: str = "",
	last_name: str = "",
	email: str = "",
	phone: str = "",
	role: str = "",
	is_primary: int = 0,
):
	data = _payload()
	property_name = data.get("property_name") or property_name
	first_name = data.get("first_name", first_name) or ""
	last_name = data.get("last_name", last_name) or ""
	email = data.get("email", email) or ""
	phone = data.get("phone", phone) or ""
	role = data.get("role", role) or ""
	is_primary = int(data.get("is_primary", is_primary) or 0)

	if not property_name:
		frappe.throw(_("property_name is required"))
	if not first_name and not last_name:
		frappe.throw(_("Contact name required"))

	c = frappe.new_doc("Contact")
	c.first_name = first_name
	c.last_name = last_name
	c.email_id = email
	c.phone = phone
	c.designation = role
	c.is_primary_contact = 1 if is_primary else 0
	c.append("links", {"link_doctype": "FT Property", "link_name": property_name})
	c.insert(ignore_permissions=True)
	frappe.db.commit()
	return {
		"ok": True,
		"contact": {
			"name": c.name,
			"person": (c.first_name or "") + (" " + c.last_name if c.last_name else ""),
			"role": c.designation,
			"phone": c.phone or c.mobile_no,
			"email": c.email_id,
		},
	}


@frappe.whitelist(methods=["POST"])
def add_contract(
	property_name: str | None = None,
	title: str = "",
	customer_name: str = "",
	start_date: str = "",
	end_date: str = "",
	active: int = 1,
	invoice_frequency: str = "monthly",
	invoice_day: int | str = 1,
	price: float | str = 0,
):
	data = _payload()
	property_name = data.get("property_name") or property_name
	title = data.get("title", title) or ""
	customer_name = data.get("customer_name", customer_name) or ""
	start_date = data.get("start_date", start_date) or None
	end_date = data.get("end_date", end_date) or None
	active = int(data.get("active", active) or 0)
	invoice_frequency = data.get("invoice_frequency", invoice_frequency) or "monthly"
	invoice_day = int(data.get("invoice_day", invoice_day) or 1)
	price = float(data.get("price", price) or 0)

	if not property_name:
		frappe.throw(_("property_name is required"))

	prop = frappe.get_doc("FT Property", property_name)
	cust = _ensure_customer(customer_name) if customer_name else prop.property_customer
	if not cust:
		frappe.throw(_("Customer required"))

	doc = frappe.get_doc(
		{
			"doctype": "FT Contract",
			"contract_title": title or (prop.property_name or prop.name),
			"contract_customer": cust,
			"contract_property": prop.name,
			"contract_start_date": start_date,
			"contract_end_date": end_date,
			"contract_active": 1 if active else 0,
			"contract_invoice_frequency": invoice_frequency,
			"contract_invoice_day": invoice_day,
			"contract_price": price,
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return {
		"ok": True,
		"contract": {
			"name": doc.name,
			"number": doc.name,
			"status": "Active" if doc.contract_active else "Inactive",
		},
	}


def _parse_when(when: str):
	if not when:
		return (None, None)
	s = str(when).strip()
	try:
		dt = get_datetime(s)  # handles 'YYYY-MM-DDTHH:MM' or datetime strings
		return (dt, None)
	except Exception:
		pass
	try:
		dt = get_datetime(s + " 00:00:00")  # bare date => required date
		return (None, dt.date())
	except Exception:
		return (None, None)


def _next_from_anchor(anchor: str | None, freq: str | None):
	if not anchor or not freq:
		return None
	try:
		dt = get_datetime(anchor)
	except Exception:
		return None
	f = (freq or "").lower()
	months = {"monthly": 1, "quarterly": 3, "six_monthly": 6, "annual": 12}.get(f)
	if months:
		return add_months(dt, months)
	if f == "one_off":
		return dt
	return None


@frappe.whitelist(methods=["POST"])
def add_schedule_rule(
	property_name: str | None = None,
	frequency: str | None = None,
	anchor_date: str | None = None,
	contract_name: str | None = None,
	timezone: str | None = None,
	rrule: str | None = None,
):
	data = _payload()
	property_name = data.get("property_name") or property_name
	frequency = data.get("frequency", frequency)
	anchor_date = data.get("anchor_date", anchor_date)
	contract_name = data.get("contract_name", contract_name)
	timezone = data.get("timezone", timezone)
	rrule = data.get("rrule", rrule)

	if not property_name or not frequency or not anchor_date:
		frappe.throw(_("property_name, frequency and anchor_date are required"))

	prop = frappe.get_doc("FT Property", property_name)
	payload = {
		"doctype": "FT Schedule Rule",
		"schedule_rule_property": prop.name,
		"schedule_rule_frequency": frequency,
		"schedule_rule_anchor_date": anchor_date,
		"schedule_rule_next_occurrence": _next_from_anchor(anchor_date, frequency),
	}
	if contract_name:
		payload["schedule_rule_contract"] = contract_name
	if timezone:
		payload["schedule_rule_timezone"] = timezone
	if rrule:
		payload["schedule_rule_rrule"] = rrule

	doc = frappe.get_doc(payload)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return {
		"ok": True,
		"schedule_rule": {
			"name": doc.name,
			"frequency": doc.schedule_rule_frequency,
			"next": (str(doc.schedule_rule_next_occurrence) if doc.schedule_rule_next_occurrence else ""),
		},
	}


# ---------- NEW: Assets, Jobs, Documents ----------


@frappe.whitelist(methods=["POST"])
def add_asset(
	property_name: str | None = None,
	asset_type: str = "",
	asset_label: str = "",
	asset_status: str = "Active",
	make: str = "",
	model: str = "",
	serial: str = "",
	identifier: str = "",
	install_date: str = "",
	standard: str = "",
	zone_name: str = "",
	zone_title: str = "",
	location_level: str = "",
	location_area: str = "",
	location_riser: str = "",
	location_cupboard: str = "",
	location_room: str = "",
	location_notes: str = "",
):
	data = _payload()
	property_name = data.get("property_name") or property_name
	asset_type_in = data.get("asset_type", asset_type) or ""
	asset_label = data.get("asset_label", asset_label) or ""
	asset_status = _norm_asset_status(data.get("asset_status", asset_status) or "Active")

	make = data.get("make", make) or ""
	model = data.get("model", model) or ""
	serial = data.get("serial", serial) or ""
	identifier = data.get("identifier", identifier) or ""
	install_date = data.get("install_date", install_date) or ""
	standard = data.get("standard", standard) or ""
	zone_name = data.get("zone_name", zone_name) or ""
	zone_title = data.get("zone_title", zone_title) or ""
	location_level = data.get("location_level", location_level) or ""
	location_area = data.get("location_area", location_area) or ""
	location_riser = data.get("location_riser", location_riser) or ""
	location_cupboard = data.get("location_cupboard", location_cupboard) or ""
	location_room = data.get("location_room", location_room) or ""
	location_notes = data.get("location_notes", location_notes) or ""

	if not property_name:
		frappe.throw(_("property_name is required"))
	if not asset_label:
		frappe.throw(_("asset_label is required"))
	if not asset_type_in:
		frappe.throw(_("asset_type is required"))

	# Ensure the Link target exists (by name/label/code); create if missing.
	at_name = _ensure_asset_type(asset_type_in)

	prop = frappe.get_doc("FT Property", property_name)

	payload = {
		"doctype": "FT Asset",
		"asset_property": prop.name,
		"asset_customer": getattr(prop, "property_customer", None),
		"asset_type": at_name,
		"asset_label": asset_label,
		"asset_status": asset_status,
	}

	# Optional fields only if they exist on this site
	def opt(field, value):
		if value and _has_field("FT Asset", field):
			payload[field] = value

	opt("asset_make", make)
	opt("asset_model", model)
	opt("asset_serial", serial)
	opt("asset_identifier", identifier)
	opt("asset_standard", standard)
	opt("asset_location_level", location_level)
	opt("asset_location_area", location_area)
	opt("asset_location_riser", location_riser)
	opt("asset_location_cupboard", location_cupboard)
	opt("asset_location_room", location_room)
	opt("asset_location_notes", location_notes)

	# install date
	if install_date and _has_field("FT Asset", "asset_install_date"):
		payload["asset_install_date"] = install_date

	# zone link
	if zone_name and _has_field("FT Asset", "asset_zone"):
		payload["asset_zone"] = zone_name

	doc = frappe.get_doc(payload)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()

	return {
		"ok": True,
		"asset": {
			"name": doc.name,
			"type": frappe.get_value("FT Asset Type", doc.asset_type, "asset_type_label") or doc.asset_type,
			"label": doc.asset_label,
			"status": doc.asset_status,
			"identifier": (getattr(doc, "asset_identifier", None) or identifier or ""),
		},
	}


@frappe.whitelist(methods=["GET"])
def get_asset(name: str):
	if not (name or "").strip():
		frappe.throw(_("name is required"))

	a = frappe.get_doc("FT Asset", name)

	# Resolve type label
	type_label = (
		frappe.get_value("FT Asset Type", a.asset_type, "asset_type_label")
		if getattr(a, "asset_type", None)
		else ""
	)

	# Zone details (optional)
	zone_title = zone_path = ""
	zone_name = getattr(a, "asset_zone", "") if _has_field("FT Asset", "asset_zone") else ""
	if zone_name:
		z = frappe.get_all(
			"FT Zone",
			filters={"name": zone_name},
			fields=["zone_title", "zone_path"],
			limit=1,
		)
		if z:
			zone_title = z[0].get("zone_title") or ""
			zone_path = z[0].get("zone_path") or ""

	def gf(field):
		return getattr(a, field) if _has_field("FT Asset", field) else None

	return {
		"name": a.name,
		"label": getattr(a, "asset_label", ""),
		"type": getattr(a, "asset_type", ""),
		"type_label": type_label or "",
		"status": getattr(a, "asset_status", "Active"),
		"make": gf("asset_make") or "",
		"model": gf("asset_model") or "",
		"serial": gf("asset_serial") or "",
		"identifier": gf("asset_identifier") or "",
		"install_date": (str(gf("asset_install_date")) if gf("asset_install_date") else ""),
		"standard": gf("asset_standard") or "",
		"zone": zone_name or "",
		"zone_title": zone_title,
		"zone_path": zone_path,
		"location_level": gf("asset_location_level") or "",
		"location_area": gf("asset_location_area") or "",
		"location_riser": gf("asset_location_riser") or "",
		"location_cupboard": gf("asset_location_cupboard") or "",
		"location_room": gf("asset_location_room") or "",
		"location_notes": gf("asset_location_notes") or "",
	}


@frappe.whitelist(methods=["POST"])
def update_asset(
	name: str | None = None,
	asset_label: str = "",
	asset_type: str = "",
	asset_status: str = "Active",
	make: str = "",
	model: str = "",
	serial: str = "",
	identifier: str = "",
	install_date: str = "",
	standard: str = "",
	zone_name: str = "",
	zone_title: str = "",
	location_level: str = "",
	location_area: str = "",
	location_riser: str = "",
	location_cupboard: str = "",
	location_room: str = "",
	location_notes: str = "",
):
	data = _payload()
	name = data.get("name") or name
	if not name:
		frappe.throw(_("name is required"))
	asset_label = data.get("asset_label", asset_label) or ""
	asset_type_in = data.get("asset_type", asset_type) or ""
	asset_status = _norm_asset_status(data.get("asset_status", asset_status) or "Active")

	make = data.get("make", make) or ""
	model = data.get("model", model) or ""
	serial = data.get("serial", serial) or ""
	identifier = data.get("identifier", identifier) or ""
	install_date = data.get("install_date", install_date) or ""
	standard = data.get("standard", standard) or ""
	zone_name = data.get("zone_name", zone_name) or ""
	zone_title = data.get("zone_title", zone_title) or ""
	location_level = data.get("location_level", location_level) or ""
	location_area = data.get("location_area", location_area) or ""
	location_riser = data.get("location_riser", location_riser) or ""
	location_cupboard = data.get("location_cupboard", location_cupboard) or ""
	location_room = data.get("location_room", location_room) or ""
	location_notes = data.get("location_notes", location_notes) or ""

	a = frappe.get_doc("FT Asset", name)

	if asset_label:
		a.asset_label = asset_label
	if asset_type_in:
		a.asset_type = _ensure_asset_type(asset_type_in)
	a.asset_status = asset_status

	def set_if(field, value):
		if _has_field("FT Asset", field):
			setattr(a, field, value)

	set_if("asset_make", make)
	set_if("asset_model", model)
	set_if("asset_serial", serial)
	set_if("asset_identifier", identifier)
	set_if("asset_standard", standard)
	set_if("asset_location_level", location_level)
	set_if("asset_location_area", location_area)
	set_if("asset_location_riser", location_riser)
	set_if("asset_location_cupboard", location_cupboard)
	set_if("asset_location_room", location_room)
	set_if("asset_location_notes", location_notes)
	if _has_field("FT Asset", "asset_install_date"):
		set_if("asset_install_date", install_date or None)

	if zone_name and _has_field("FT Asset", "asset_zone"):
		set_if("asset_zone", zone_name)

	a.save(ignore_permissions=True)
	frappe.db.commit()
	return {"ok": True}


@frappe.whitelist(methods=["POST"], allow_guest=True)
def add_credential(
	property_name: str | None = None,
	credential_type: str | None = None,
	validity_days: int | str = 0,
	blocking: int = 0,
	notes: str = "",
):
	# Require an authenticated session even though allow_guest=True (bypasses CSRF)
	if frappe.session.user == "Guest":
		raise frappe.PermissionError("Login required")

	data = _payload()
	property_name = data.get("property_name") or property_name
	credential_type = data.get("credential_type", credential_type)
	validity_days = int(data.get("validity_days", validity_days) or 0)
	blocking = 1 if int(data.get("blocking", blocking) or 0) else 0
	notes = data.get("notes", notes) or ""

	if not property_name or not credential_type:
		frappe.throw(_("property_name and credential_type are required"))

	prop = frappe.get_doc("FT Property", property_name)

	meta = frappe.get_meta("FT Property")
	table_field = meta.get_field("property_credentials")
	if not table_field:
		frappe.throw(
			_("FT Property missing child table 'property_credentials' (FT Property Credential Requirement).")
		)

	row = {
		"doctype": "FT Property Credential Requirement",
		"property_credential_type": credential_type,
		"property_credential_validity_days": validity_days,
		"property_credential_blocking": blocking,
		"property_credential_notes": notes,
	}
	prop.append("property_credentials", row)
	prop.save(ignore_permissions=True)
	frappe.db.commit()
	return {"ok": True}


@frappe.whitelist(methods=["POST"])
def add_job(
	property_name: str | None = None,
	title: str = "",
	when: str = "",
	status: str = "Scheduled",
):
	data = _payload()
	property_name = data.get("property_name") or property_name
	title = data.get("title", title) or ""
	when = data.get("when", when) or ""
	status = data.get("status", status) or "Scheduled"
	if not property_name or not title:
		frappe.throw(_("property_name and title are required"))

	start_dt, req_date = _parse_when(when)
	payload = {
		"doctype": "FT Job",
		"job_property": property_name,
		"job_title": title,
		"job_status": status,
	}
	if start_dt:
		payload["job_scheduled_start"] = start_dt
	if req_date:
		payload["job_required_date"] = req_date

	doc = frappe.get_doc(payload)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return {
		"ok": True,
		"job": {
			"name": doc.name,
			"title": doc.job_title,
			"status": doc.job_status,
			"when": start_dt or req_date or "",
		},
	}


@frappe.whitelist(methods=["POST"])
def add_document(property_name: str | None = None, title: str = "", file_url: str = ""):
	data = _payload()
	property_name = data.get("property_name") or property_name
	title = data.get("title", title) or ""
	file_url = data.get("file_url", file_url) or ""
	if not property_name or not title:
		frappe.throw(_("property_name and title are required"))

	doc = frappe.get_doc(
		{
			"doctype": "FT Document Vault",
			"document_vault_property": property_name,
			"document_vault_title": title,
			"document_vault_file": file_url,
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return {
		"ok": True,
		"document": {
			"name": doc.name,
			"title": doc.document_vault_title,
			"url": doc.document_vault_file,
		},
	}
