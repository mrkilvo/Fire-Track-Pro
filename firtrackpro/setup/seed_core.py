import frappe


def _upsert(doctype, name, values):
    doc = (
        frappe.get_doc(doctype, name)
        if frappe.db.exists(doctype, name)
        else frappe.new_doc(doctype)
    )
    doc.update(values)
    if not doc.name:
        doc.name = name
    doc.flags.ignore_permissions = True
    doc.save()
    return doc


@frappe.whitelist()
def seed():
    std = _upsert(
        "ft_standard",
        "AS1851-2018",
        {
            "standard_code": "AS1851",
            "standard_label": "AS 1851 Routine Service of Fire Protection Systems and Equipment",
            "standard_version": "2018",
        },
    )

    suite_annual_pump = _upsert(
        "ft_test_suite",
        "AS1851-2018 Pump Annual",
        {
            "test_suite_code": "AS1851-2018-pump-annual",
            "test_suite_label": "AS1851-2018 Pump Annual",
            "test_suite_standard": std.name,
            "test_suite_frequency": "annual",
            "test_suite_table_ref": "Table 10",
        },
    )

    suite_monthly_pump = _upsert(
        "ft_test_suite",
        "AS1851-2018 Pump Monthly",
        {
            "test_suite_code": "AS1851-2018-pump-monthly",
            "test_suite_label": "AS1851-2018 Pump Monthly",
            "test_suite_standard": std.name,
            "test_suite_frequency": "monthly",
            "test_suite_table_ref": "Table 10",
        },
    )

    def add_item(
        parent_suite_name,
        code,
        desc,
        requires_reading=0,
        uom="",
        min_v=None,
        max_v=None,
        pass_required=1,
        defect_on_fail=1,
    ):
        suite = frappe.get_doc("ft_test_suite", parent_suite_name)
        suite.append(
            "test_suite_items",
            {
                "test_item_code": code,
                "test_item_description": desc,
                "test_item_requires_reading": requires_reading,
                "test_item_uom": uom,
                "test_item_min": min_v,
                "test_item_max": max_v,
                "test_item_pass_required": pass_required,
                "test_item_defect_on_fail": defect_on_fail,
            },
        )
        suite.flags.ignore_permissions = True
        suite.save()

    add_item(suite_annual_pump.name, "visual", "General visual condition")
    add_item(suite_annual_pump.name, "start_auto", "Auto start from pressure drop")
    add_item(
        suite_annual_pump.name,
        "duty_point",
        "Verify duty flow and head",
        1,
        "L/s",
        None,
        None,
        1,
        1,
    )
    add_item(suite_annual_pump.name, "run_time", "Minimum run time achieved")

    add_item(suite_monthly_pump.name, "visual", "General visual condition")
    add_item(suite_monthly_pump.name, "start_manual", "Manual start verified")

    _upsert(
        "ft_asset_type",
        "sprinkler_pump_diesel",
        {
            "asset_type_code": "sprinkler_pump_diesel",
            "asset_type_label": "Sprinkler Pump (Diesel)",
            "asset_type_standard": std.name,
            "asset_type_default_suite": suite_annual_pump.name,
            "asset_type_default_frequency": "annual",
            "asset_type_description": "Diesel-driven sprinkler pump",
        },
    )

    _upsert(
        "ft_asset_type",
        "sprinkler_pump_electric",
        {
            "asset_type_code": "sprinkler_pump_electric",
            "asset_type_label": "Sprinkler Pump (Electric)",
            "asset_type_standard": std.name,
            "asset_type_default_suite": suite_annual_pump.name,
            "asset_type_default_frequency": "annual",
            "asset_type_description": "Electric-driven sprinkler pump",
        },
    )

    _upsert(
        "ft_asset_type",
        "fire_panel",
        {
            "asset_type_code": "fire_panel",
            "asset_type_label": "Fire Indicator Panel",
            "asset_type_standard": std.name,
            "asset_type_default_suite": suite_monthly_pump.name,
            "asset_type_default_frequency": "monthly",
            "asset_type_description": "Fire indicator panel",
        },
    )

    _upsert(
        "ft_asset_type",
        "hydrant_booster",
        {
            "asset_type_code": "hydrant_booster",
            "asset_type_label": "Hydrant Booster",
            "asset_type_standard": std.name,
            "asset_type_default_suite": suite_monthly_pump.name,
            "asset_type_default_frequency": "monthly",
            "asset_type_description": "Hydrant booster assembly",
        },
    )
