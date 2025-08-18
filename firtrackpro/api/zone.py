import frappe


@frappe.whitelist(methods=["GET"], allow_guest=True)
def search(property: str | None = None, q: str = "", limit: int = 10):
	q = (q or "").strip()
	try:
		limit = int(limit or 10)
	except Exception:
		limit = 10

	if not property or not q:
		return []

	rows = frappe.get_all(
		"FT Zone",
		filters={
			"zone_property": property,
			"zone_title": ["like", f"%{q}%"],
		},
		fields=["name", "zone_title", "zone_path"],
		order_by="zone_title asc",
		limit_page_length=limit,
		ignore_permissions=True,
	)
	return [
		{
			"name": r["name"],
			"title": r.get("zone_title") or r["name"],
			"path": r.get("zone_path") or "",
		}
		for r in rows
	]
