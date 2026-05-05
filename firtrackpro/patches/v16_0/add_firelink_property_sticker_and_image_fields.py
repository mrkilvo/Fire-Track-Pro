import frappe


def execute():
	for doctype in ("FT Property", "FL Property"):
		if not frappe.db.has_column(doctype, "firelink_sticker_id"):
			frappe.db.add_column(doctype, "firelink_sticker_id", "varchar(140)")
		if not frappe.db.has_column(doctype, "property_front_image"):
			frappe.db.add_column(doctype, "property_front_image", "varchar(140)")
