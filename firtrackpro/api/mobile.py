import frappe


@frappe.whitelist()
def get_ft_severity_options():
	rows = frappe.get_all(
		"FT Severity", fields=["name", "severity"], order_by="modified desc", limit_page_length=200
	)
	out = []
	for r in rows:
		label = (r.get("severity") or r.get("name") or "").strip()
		if label:
			out.append(label)
	return sorted(list(set(out)))
