import frappe
from frappe.utils import today


def get_settings_context():
	try:
		d = frappe.get_single("FireTrack Pro Settings")
		return frappe._dict(
			{
				"system_name": getattr(d, "system_name", None) or "FireTrack Pro",
				"logo": getattr(d, "logo", None) or "/assets/firtrackpro/images/firetrack-logo.png",
				"favicon": getattr(d, "favicon", None) or "/assets/firtrackpro/images/favicon.png",
				"primary_color": getattr(d, "primary_color", None) or "#EF4444",
				"accent_color": getattr(d, "accent_color", None) or "#0EA5E9",
				"footer_note": getattr(d, "footer_note", None)
				or "© 2025 FireTrack Pro. All rights reserved.",
				"support_email": getattr(d, "support_email", None) or "support@firetrackpro.com.au",
				"currency": getattr(d, "currency", None) or "AUD",
				"show_firelink": int(getattr(d, "show_firelink", 1) or 1),
				"show_free_note": int(getattr(d, "show_free_note", 0) or 0),
				"last_updated": str(getattr(d, "last_updated", today())),
			}
		)
	except Exception:
		return frappe._dict(
			{
				"system_name": "FireTrack Pro",
				"logo": "/assets/firtrackpro/images/firetrack-logo.png",
				"favicon": "/assets/firtrackpro/images/favicon.png",
				"primary_color": "#EF4444",
				"accent_color": "#0EA5E9",
				"footer_note": "© 2025 FireTrack Pro. All rights reserved.",
				"support_email": "support@firetrackpro.com.au",
				"currency": "AUD",
				"show_firelink": 1,
				"show_free_note": 0,
				"last_updated": today(),
			}
		)


def count_or_demo(doctype, filters=None, demo=0):
	try:
		if not frappe.db.has_table(doctype):
			return demo
		return frappe.db.count(doctype, filters or {})
	except Exception:
		return demo


def list_or_demo(doctype, filters=None, fields=None, order_by=None, limit=None, demo=None):
	try:
		if not frappe.db.has_table(doctype):
			return demo or []
		return frappe.get_all(doctype, filters or {}, fields or ["*"], order_by=order_by, limit=limit)
	except Exception:
		return demo or []


def doc_or_demo(doctype, name, demo):
	try:
		if not frappe.db.has_table(doctype):
			return frappe._dict(demo)
		if not frappe.db.exists(doctype, name):
			return frappe._dict(demo)
		return frappe.get_doc(doctype, name)
	except Exception:
		return frappe._dict(demo)
