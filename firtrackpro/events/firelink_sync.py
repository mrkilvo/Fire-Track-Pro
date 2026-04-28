from __future__ import annotations

from typing import Any

import frappe

from firtrackpro.api import integrations


def _safe_str(value: Any) -> str:
	return str(value or "").strip()


def _address_payload_for_property(prop_doc) -> dict[str, Any]:
	address_name = _safe_str(getattr(prop_doc, "property_address", ""))
	address_doc = None
	if address_name and frappe.db.exists("Address", address_name):
		address_doc = frappe.get_doc("Address", address_name)

	address_title = _safe_str(getattr(address_doc, "address_title", "")) if address_doc else ""
	line1 = _safe_str(getattr(address_doc, "address_line1", "")) if address_doc else ""
	line2 = _safe_str(getattr(address_doc, "address_line2", "")) if address_doc else ""
	city = _safe_str(getattr(address_doc, "city", "")) if address_doc else ""
	state = _safe_str(getattr(address_doc, "state", "")) if address_doc else ""
	pincode = _safe_str(getattr(address_doc, "pincode", "")) if address_doc else ""
	country = _safe_str(getattr(address_doc, "country", "")) if address_doc else ""

	if not line1:
		line1 = _safe_str(getattr(prop_doc, "ft_property_address_line1", "")) or _safe_str(
			getattr(prop_doc, "ftp_property_address_line1", "")
		)
	if not line1:
		line1 = _safe_str(getattr(prop_doc, "property_name", ""))

	if not address_title:
		address_title = _safe_str(getattr(prop_doc, "property_name", "")) or line1
	if not country:
		country = "Australia"

	return {
		"local_property_id": _safe_str(getattr(prop_doc, "name", "")),
		"firelink_property_id": _safe_str(getattr(prop_doc, "firelink_uid", "")) or None,
		"property_display_name": _safe_str(getattr(prop_doc, "property_name", "")),
		"property_lat": getattr(prop_doc, "property_lat", None),
		"property_lng": getattr(prop_doc, "property_lng", None),
		"address_title": address_title,
		"address_line1": line1,
		"address_line2": line2 or None,
		"city": city or None,
		"state": state or None,
		"pincode": pincode or None,
		"country": country,
	}


def _ensure_property_link(prop_doc) -> str:
	payload = _address_payload_for_property(prop_doc)
	if not _safe_str(payload.get("address_line1")):
		return ""
	result = integrations.firelink_property_sync(**payload) or {}
	firelink_property_id = _safe_str(result.get("firelink_property_id"))
	if firelink_property_id and firelink_property_id != _safe_str(getattr(prop_doc, "firelink_uid", "")):
		frappe.db.set_value(
			"FT Property", prop_doc.name, "firelink_uid", firelink_property_id, update_modified=False
		)
	return firelink_property_id


def sync_property_after_save(doc, method=None):
	try:
		_ensure_property_link(doc)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"FireLink property sync failed: {doc.doctype} {doc.name}")


def sync_asset_after_save(doc, method=None):
	try:
		property_id = _safe_str(getattr(doc, "asset_property", ""))
		if not property_id or not frappe.db.exists("FT Property", property_id):
			return
		prop_doc = frappe.get_doc("FT Property", property_id)
		firelink_property_id = _safe_str(getattr(prop_doc, "firelink_uid", "")) or _ensure_property_link(
			prop_doc
		)
		if not firelink_property_id:
			return

		result = (
			integrations.firelink_asset_sync(
				local_asset_id=_safe_str(doc.name),
				firelink_property_id=firelink_property_id,
				asset_label=_safe_str(getattr(doc, "asset_label", "")),
				asset_type_code=_safe_str(getattr(doc, "asset_type", "")),
				asset_serial=_safe_str(getattr(doc, "asset_serial", "")),
				asset_identifier=_safe_str(getattr(doc, "asset_identifier", "")),
				asset_status=_safe_str(getattr(doc, "asset_status", "")),
			)
			or {}
		)
		firelink_asset_id = _safe_str(result.get("firelink_asset_id"))
		if firelink_asset_id and firelink_asset_id != _safe_str(getattr(doc, "asset_firelink_uid", "")):
			frappe.db.set_value(
				"FT Asset", doc.name, "asset_firelink_uid", firelink_asset_id, update_modified=False
			)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"FireLink asset sync failed: {doc.doctype} {doc.name}")


def sync_defect_after_save(doc, method=None):
	try:
		property_id = _safe_str(getattr(doc, "defect_property", ""))
		if not property_id or not frappe.db.exists("FT Property", property_id):
			return
		prop_doc = frappe.get_doc("FT Property", property_id)
		firelink_property_id = _safe_str(getattr(prop_doc, "firelink_uid", "")) or _ensure_property_link(
			prop_doc
		)
		if not firelink_property_id:
			return

		firelink_asset_id = ""
		linked_asset_id = _safe_str(getattr(doc, "defect_asset", ""))
		if linked_asset_id and frappe.db.exists("FT Asset", linked_asset_id):
			firelink_asset_id = _safe_str(
				frappe.db.get_value("FT Asset", linked_asset_id, "asset_firelink_uid")
			)

		result = (
			integrations.firelink_defect_sync(
				local_defect_id=_safe_str(doc.name),
				firelink_property_id=firelink_property_id,
				firelink_asset_id=firelink_asset_id or None,
				defect_template_code=_safe_str(getattr(doc, "defect_template", "")),
				defect_severity=_safe_str(getattr(doc, "defect_severity", "")),
				defect_status=_safe_str(getattr(doc, "defect_status", "")),
				defect_summary=_safe_str(getattr(doc, "defect_description", ""))[:140],
			)
			or {}
		)
		firelink_defect_id = _safe_str(result.get("firelink_defect_id"))
		if firelink_defect_id and firelink_defect_id != _safe_str(getattr(doc, "defect_firelink_uid", "")):
			frappe.db.set_value(
				"FT Defect", doc.name, "defect_firelink_uid", firelink_defect_id, update_modified=False
			)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"FireLink defect sync failed: {doc.doctype} {doc.name}")
