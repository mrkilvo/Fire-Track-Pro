import frappe


def _get_primary_contact_for_user(user_id: str, email: str):
	contact = None
	try:
		if frappe.db.has_table("Contact"):
			contact = (
				frappe.db.get_value("Contact", {"user": user_id}, "name")
				or frappe.db.get_value("Contact", {"email_id": email}, "name")
				or frappe.db.get_value("Contact Email", {"email_id": email}, "parent")
			)
	except Exception:
		contact = None
	return contact


def _get_single_address_for_contact(contact_name: str):
	"""Return a single primary address for the contact if any."""
	if not contact_name:
		return None

	try:
		if not frappe.db.has_table("Address"):
			return None

		# Prefer any Address linked via Dynamic Link (first match)
		addr_name = frappe.db.get_value(
			"Dynamic Link",
			{
				"link_doctype": "Contact",
				"link_name": contact_name,
				"parenttype": "Address",
				"parentfield": "links",
			},
			"parent",
		)
		if not addr_name:
			return None

		fields = [
			"name",
			"address_title",
			"address_type",
			"address_line1",
			"address_line2",
			"city",
			"state",
			"pincode",
			"country",
			"email_id",
			"phone",
		]
		# Add optional lat/lon fields if exist
		meta = frappe.get_meta("Address")
		for f in (
			"latitude",
			"longitude",
			"lat",
			"lon",
			"geo_latitude",
			"geo_longitude",
		):
			if meta.has_field(f):
				fields.append(f)

		return frappe.get_value("Address", addr_name, fields, as_dict=True)
	except Exception:
		return None


def get_context(context):
	user_id = frappe.session.user

	# --- User profile (demo-first) ---
	try:
		u = frappe.get_doc("User", user_id)
		profile = {
			"email": u.name or "",
			"first_name": u.first_name or "",
			"last_name": u.last_name or "",
			"full_name": u.full_name or u.first_name or u.name,
			"phone": u.phone or "",
			"mobile_no": getattr(u, "mobile_no", "") or "",
			"time_zone": u.time_zone or "",
			"language": u.language or "",
			"user_image": u.user_image or "",
		}
	except Exception:
		profile = {
			"email": user_id,
			"first_name": "Demo",
			"last_name": "User",
			"full_name": "Demo User",
			"phone": "+61 3 9999 9999",
			"mobile_no": "+61 400 000 000",
			"time_zone": "Australia/Melbourne",
			"language": "en",
			"user_image": "",
		}

	# --- Licences/Accreditations (demo-first) ---
	licences = []
	try:
		if frappe.db.has_table("User Accreditation"):
			licences = frappe.get_all(
				"User Accreditation",
				{"user": user_id},
				["name", "accreditation_type", "accreditation_number", "expiry_date"],
				order_by="expiry_date asc",
			)
	except Exception:
		licences = []
	if not licences:
		licences = [
			{
				"name": "LIC-001",
				"accreditation_type": "FPAA Inspect/Test",
				"accreditation_number": "FPA-12345",
				"expiry_date": "2026-06-30",
			},
			{
				"name": "LIC-002",
				"accreditation_type": "Working at Heights",
				"accreditation_number": "WAH-99887",
				"expiry_date": "2025-12-31",
			},
		]

	# --- Address (single; real if available) ---
	address = None
	try:
		contact_name = _get_primary_contact_for_user(user_id, profile.get("email"))
		address = _get_single_address_for_contact(contact_name)
	except Exception:
		address = None
	if not address:
		address = {
			"name": "ADDR-DEMO",
			"address_title": "Home",
			"address_line1": "10 Demo Street",
			"address_line2": "",
			"city": "Melbourne",
			"state": "VIC",
			"pincode": "3000",
			"country": "Australia",
			"phone": profile.get("phone"),
			"email_id": profile.get("email"),
			"lat": "-37.8136",
			"lon": "144.9631",
		}

	# --- Signature (signature field only; no avatar fallback) ---
	signature_url = "/files/sample-signature.png"
	try:
		user_doc = frappe.get_doc("User", user_id)
		for f in ["user_signature", "signature", "signature_image"]:
			if user_doc.meta.has_field(f) and getattr(user_doc, f):
				signature_url = getattr(user_doc, f)
				break
	except Exception:
		pass

	context.profile = frappe._dict(profile)
	context.licences = licences
	context.address = frappe._dict(address)
	context.signature_url = signature_url
	context.csrf_token = frappe.sessions.get_csrf_token()
	return context
