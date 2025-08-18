import frappe


def _resolve_asset_type(asset_type_code=None, asset_type_label=None):
	if asset_type_code:
		by_code = frappe.db.get_value("ft_asset_type", {"asset_type_code": asset_type_code}, "name")
		if by_code:
			return by_code
		if frappe.db.exists("ft_asset_type", asset_type_code):
			return asset_type_code
	if asset_type_label:
		by_label = frappe.db.get_value("ft_asset_type", {"asset_type_label": asset_type_label}, "name")
		if by_label:
			return by_label
	return None


@frappe.whitelist()
def list_asset_types():
	return frappe.get_all(
		"ft_asset_type",
		fields=[
			"name",
			"asset_type_code",
			"asset_type_label",
			"asset_type_default_suite",
			"asset_type_default_frequency",
		],
		order_by="asset_type_label asc",
		ignore_permissions=1,
	)


@frappe.whitelist()
def list_zones(property_name):
	return frappe.get_all(
		"ft_property_zone",
		filters={"property_zone_property": property_name},
		fields=[
			"name",
			"property_zone_parent_zone",
			"property_zone_title",
			"property_zone_path",
		],
		order_by="property_zone_path asc",
		ignore_permissions=1,
	)


@frappe.whitelist()
def list_assets(property_name):
	fields = [
		"name",
		"asset_label",
		"asset_type",
		"asset_zone",
		"asset_location_level",
		"asset_location_area",
		"asset_location_riser",
		"asset_location_cupboard",
		"asset_identifier",
		"asset_serial",
		"asset_status",
		"asset_last_tested",
		"asset_next_due",
	]
	return frappe.get_all(
		"ft_asset",
		filters={"asset_property": property_name},
		fields=fields,
		order_by="asset_label asc",
		ignore_permissions=1,
	)


@frappe.whitelist()
def get_asset(name):
	doc = frappe.get_doc("ft_asset", name)
	doc.flags.ignore_permissions = True
	return doc.as_dict()


@frappe.whitelist()
def create_asset(
	asset_property,
	asset_label,
	asset_type_code=None,
	asset_type_label=None,
	asset_zone=None,
	asset_identifier=None,
	asset_serial=None,
	asset_location_level=None,
	asset_location_area=None,
	asset_location_riser=None,
	asset_location_cupboard=None,
	driver_type=None,
):
	at = _resolve_asset_type(asset_type_code, asset_type_label)
	if not at:
		frappe.throw("Asset Type not found")

	property_doc = frappe.get_doc("ft_property", asset_property)
	property_doc.flags.ignore_permissions = True
	customer = property_doc.property_customer

	doc = frappe.new_doc("ft_asset")
	doc.asset_label = asset_label
	doc.asset_property = asset_property
	doc.asset_customer = customer
	doc.asset_type = at
	doc.asset_zone = asset_zone
	doc.asset_identifier = asset_identifier
	doc.asset_serial = asset_serial
	doc.asset_location_level = asset_location_level
	doc.asset_location_area = asset_location_area
	doc.asset_location_riser = asset_location_riser
	doc.asset_location_cupboard = asset_location_cupboard
	doc.flags.ignore_permissions = True
	doc.save()

	at_code = frappe.db.get_value("ft_asset_type", at, "asset_type_code")
	if at_code in ("sprinkler_pump_diesel", "sprinkler_pump_electric"):
		pp = frappe.new_doc("ft_pump_profile")
		pp.pump_profile_asset = doc.name
		pp.pump_profile_driver_type = (
			"diesel" if (driver_type or (at_code.endswith("diesel"))) else "electric"
		)
		pp.flags.ignore_permissions = True
		pp.save()

	return {"name": doc.name}
