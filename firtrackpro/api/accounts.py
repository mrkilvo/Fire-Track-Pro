import base64

import frappe
from frappe.utils.file_manager import save_file
from frappe.utils.password import check_password, update_password

# -----------------------------
# Helpers
# -----------------------------

SIGNATURE_FIELDS = [
	"user_signature",
	"signature",
	"signature_image",
]  # any one of these on User


def _get_signature_field_on_user():
	"""Return the first available signature field on User DocType."""
	meta = frappe.get_meta("User")
	for f in SIGNATURE_FIELDS:
		if meta.has_field(f):
			return f
	return None


def _ensure_contact_for_user(user_id: str):
	"""Ensure we have a Contact linked to this user; return contact name."""
	email = user_id
	contact = None
	if frappe.db.has_table("Contact"):
		contact = (
			frappe.db.get_value("Contact", {"user": user_id}, "name")
			or frappe.db.get_value("Contact", {"email_id": email}, "name")
			or frappe.db.get_value("Contact Email", {"email_id": email}, "parent")
		)
		if not contact:
			# Create a minimal Contact for the user
			user_doc = frappe.get_doc("User", user_id)
			first_name = user_doc.first_name or user_doc.full_name or user_doc.name
			c = frappe.get_doc(
				{
					"doctype": "Contact",
					"first_name": first_name,
					"user": user_id,
					"email_id": user_doc.name,
				}
			)
			c.append("email_ids", {"email_id": user_doc.name, "is_primary": 1})
			c.insert(ignore_permissions=True)
			contact = c.name
	return contact


# -----------------------------
# Profile
# -----------------------------


@frappe.whitelist()
def update_profile(
	first_name=None,
	last_name=None,
	phone=None,
	mobile_no=None,
	time_zone=None,
	language=None,
):
	user = frappe.session.user
	doc = frappe.get_doc("User", user)
	if first_name is not None:
		doc.first_name = first_name
	if last_name is not None:
		doc.last_name = last_name
	if phone is not None:
		doc.phone = phone
	if mobile_no is not None:
		doc.mobile_no = mobile_no
	if time_zone is not None:
		doc.time_zone = time_zone
	if language is not None:
		doc.language = language
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"message": "ok"}


@frappe.whitelist()
def change_password(current_password, new_password):
	user = frappe.session.user
	check_password(user, current_password)
	update_password(user, new_password)
	frappe.db.commit()
	return {"message": "ok"}


# -----------------------------
# Avatar & Signature
# -----------------------------


@frappe.whitelist()
def upload_avatar():
	"""Upload an avatar; saves ONLY to user_image."""
	user = frappe.session.user
	file = frappe.request.files.get("file")
	if not file:
		frappe.throw("No file")
	content = file.stream.read()
	fname = file.filename
	saved = save_file(fname, content, "User", user, is_private=0)

	doc = frappe.get_doc("User", user)
	if doc.meta.has_field("user_image"):
		doc.user_image = saved.file_url
		doc.save(ignore_permissions=True)
		frappe.db.commit()
	return {"file_url": saved.file_url}


@frappe.whitelist()
def upload_signature():
	"""Upload a signature image file; saves ONLY to a signature field on User."""
	user = frappe.session.user
	sig_field = _get_signature_field_on_user()
	if not sig_field:
		frappe.throw(
			"User signature field not found. Add an Attach Image field named 'user_signature' (or 'signature'/'signature_image') on User."
		)

	file = frappe.request.files.get("file")
	if not file:
		frappe.throw("No file")
	content = file.stream.read()
	fname = file.filename
	saved = save_file(fname, content, "User", user, is_private=0)

	doc = frappe.get_doc("User", user)
	setattr(doc, sig_field, saved.file_url)
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"file_url": saved.file_url}


@frappe.whitelist()
def save_signature_dataurl(data_url: str):
	"""Save a drawn signature (data:image/png;base64,...) ONLY to a signature field."""
	user = frappe.session.user
	sig_field = _get_signature_field_on_user()
	if not sig_field:
		frappe.throw(
			"User signature field not found. Add an Attach Image field named 'user_signature' (or 'signature'/'signature_image') on User."
		)

	if not data_url or "," not in data_url:
		frappe.throw("Invalid signature data")

	header, encoded = data_url.split(",", 1)
	try:
		content = base64.b64decode(encoded)
	except Exception:
		frappe.throw("Invalid base64 payload")

	fname = f"signature-{frappe.utils.now_datetime().strftime('%Y%m%d%H%M%S')}.png"
	saved = save_file(fname, content, "User", user, is_private=0)

	doc = frappe.get_doc("User", user)
	setattr(doc, sig_field, saved.file_url)
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"file_url": saved.file_url}


# -----------------------------
# Address (single for user)
# -----------------------------


@frappe.whitelist()
def save_user_address(
	address_name: str = "",
	address_title: str = "Primary",
	address_line1: str = "",
	address_line2: str = "",
	city: str = "",
	state: str = "",
	pincode: str = "",
	country: str = "Australia",
	lat: str = "",
	lon: str = "",
):
	"""Create or update ONE personal Address linked to the user's Contact."""
	user = frappe.session.user
	contact = _ensure_contact_for_user(user)

	# Create or update Address
	if address_name and frappe.db.exists("Address", address_name):
		doc = frappe.get_doc("Address", address_name)
	else:
		doc = frappe.new_doc("Address")
		doc.address_title = address_title or "Primary"
		doc.address_type = "Personal"

	doc.address_line1 = address_line1
	doc.address_line2 = address_line2
	doc.city = city
	doc.state = state
	doc.pincode = pincode
	doc.country = country

	# Optional lat/lon fields (if exist on Address)
	for fld, val in (
		("latitude", lat),
		("longitude", lon),
		("lat", lat),
		("lon", lon),
		("geo_latitude", lat),
		("geo_longitude", lon),
	):
		if doc.meta.has_field(fld):
			setattr(doc, fld, val)

	# Link to Contact (avoid duplicate links)
	if hasattr(doc, "links"):
		doc.links = [l for l in doc.links if not (l.link_doctype == "Contact" and l.link_name == contact)]
		if contact:
			doc.append("links", {"link_doctype": "Contact", "link_name": contact})

	# Prefer to mark as primary if field exists
	if doc.meta.has_field("is_primary_address"):
		doc.is_primary_address = 1

	if doc.get("name"):
		doc.save(ignore_permissions=True)
	else:
		doc.insert(ignore_permissions=True)

	frappe.db.commit()
	return {"name": doc.name}


# -----------------------------
# Licences / Accreditations
# -----------------------------


@frappe.whitelist()
def add_accreditation(accreditation_type, accreditation_number, expiry_date):
	"""Create a User Accreditation if the table exists; otherwise no-op demo."""
	user = frappe.session.user
	if frappe.db.has_table("User Accreditation"):
		doc = frappe.get_doc(
			{
				"doctype": "User Accreditation",
				"user": user,
				"accreditation_type": accreditation_type,
				"accreditation_number": accreditation_number,
				"expiry_date": expiry_date,
			}
		)
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		return {"name": doc.name}
	return {"name": None}
