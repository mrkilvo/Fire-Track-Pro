import frappe


@frappe.whitelist(methods=["GET"], allow_guest=True)
def search(q: str | None = None, limit: int = 10):
    q = (q or "").strip()
    try:
        limit = max(1, min(25, int(limit or 10)))
    except Exception:
        limit = 10
    if not q:
        return []
    rows = frappe.get_all(
        "FT Asset Type",
        filters={"asset_type_label": ["like", f"%{q}%"]},
        fields=["name", "asset_type_label"],
        order_by="asset_type_label asc",
        limit=limit,
    )
    return [{"id": r.name, "label": r.asset_type_label} for r in rows]
