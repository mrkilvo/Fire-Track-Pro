import hashlib
import json

import frappe
from frappe.query_builder import Table
from frappe.query_builder.functions import Lower
from pypika.terms import CustomFunction

LOCATE = CustomFunction("LOCATE")


@frappe.whitelist(methods=["GET"], allow_guest=True)
def search(q: str | None = None, limit: int = 8):
	"""
	Lightweight Customer search for the portal with:
	- case-insensitive matching on name and customer_name
	- prefix boost (names starting with the query rank first)
	- de-duplication
	- tiny 2-minute cache
	Returns: [{ id, label, group, territory }]
	"""
	q = (q or "").strip()
	if not q:
		return []

	try:
		limit = max(1, min(20, int(limit or 8)))
	except Exception:
		limit = 8

	cache_key = (
		"cust:search:"
		+ hashlib.sha1(json.dumps({"q": q.lower(), "l": limit}, sort_keys=True).encode()).hexdigest()
	)
	cached = frappe.cache().get_value(cache_key)
	if cached:
		try:
			return json.loads(cached)
		except Exception:
			pass

	Customer = Table("tabCustomer")
	q_lower = q.lower()

	# Build query (case-insensitive LIKE on name/customer_name)
	qry = (
		frappe.qb.from_(Customer)
		.select(
			Customer.name,
			Customer.customer_name,
			Customer.customer_group,
			Customer.territory,
			LOCATE(q, Customer.customer_name).as_("pos_name"),
			LOCATE(q, Customer.name).as_("pos_id"),
		)
		.where(
			(Lower(Customer.customer_name).like(f"%{q_lower}%")) | (Lower(Customer.name).like(f"%{q_lower}%"))
		)
		# Order: prefix matches first, then by customer_name asc
		.orderby("pos_name")  # 1 means starts-with, >1 is later, 0 if not found
		.orderby("pos_id")
		.orderby(Customer.customer_name)
		.limit(limit * 2)  # fetch a few extra before de-dupe
	)

	rows = frappe.qb.run(qry, as_dict=True)

	# De-dupe by primary key
	seen = set()
	out = []
	for r in rows:
		name = r["name"]
		if name in seen:
			continue
		seen.add(name)
		out.append(
			{
				"id": name,
				"label": r.get("customer_name") or name,
				"group": r.get("customer_group") or "",
				"territory": r.get("territory") or "",
			}
		)
		if len(out) >= limit:
			break

	frappe.cache().set_value(cache_key, json.dumps(out), expires_in_sec=120)
	return out
