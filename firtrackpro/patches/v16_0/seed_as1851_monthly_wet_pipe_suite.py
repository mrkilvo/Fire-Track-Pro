import frappe


STANDARD_CODE = "AS1851-2012-T2.4.2.1"
STANDARD_LABEL = "AS 1851:2012 Table 2.4.2.1"
STANDARD_VERSION = "2012"
STANDARD_DESC = "Monthly routine service schedule - automatic fire sprinkler systems (wet pipe systems)."

SUITE_CODE = "AS1851-WET-MONTHLY"
SUITE_LABEL = "AS1851 Monthly - Wet Pipe Systems"
SUITE_TABLE_REF = "Table 2.4.2.1"


ITEMS = [
    ("1.1", "Control valve assembly", "CHECK control valve assembly area is unobstructed and free of adverse conditions.", 0, "", 1, 1),
    ("1.2", "Sprinkler spares, sprinklers and sprinkler spanner", "CHECK spare sprinklers and matching spanner are available in appropriate quantity/type.", 0, "", 1, 1),
    ("1.3", "Signage", "CHECK required signage is undamaged, legible and appropriately located.", 0, "", 1, 1),
    ("1.4", "Fire brigade booster connection", "CHECK booster connection/enclosure is unobstructed and coupling type meets local brigade requirements.", 0, "", 1, 1),
    ("1.5", "Main stop valves and alarm cocks", "INSPECT each main stop valve and alarm cock is secured open and correctly labelled.", 0, "", 1, 1),
    ("1.6", "Pump starting devices isolating valve", "CHECK each isolating valve to each automatic pump start device is locked open.", 0, "", 1, 1),
    ("1.7", "Pressure switches", "CHECK each pressure switch cover is in place, labelled, secure and free of adverse condition.", 0, "", 1, 1),
    ("1.8", "Alarm signalling equipment (ASE) (stand-alone)", "CHECK ASE is securely mounted, functional and not indicating alarm/fault/loss/isolated.", 0, "", 1, 1),
    ("1.9", "Sprinkler system interface to other systems", "CHECK sprinkler alarm interface with other systems is not isolated, inhibited or disabled.", 0, "", 1, 1),
    ("1.10", "Water supply stop valves", "OPERATE all applicable water supply stop valves and VERIFY indicators are secure and correct.", 0, "", 1, 1),
    ("1.11", "System pressure gauge readings before alarm function test", "RECORD reading from each pressure gauge and VERIFY readings are within required ranges.", 1, "kPa", 1, 1),
    ("1.12", "Control assembly/alarm gong/alarm initiating device/fire brigade alarm test", "OPERATE alarm test valve, RECORD operation time and RESET alarm test valve on completion.", 1, "s", 1, 1),
    ("1.13", "Alarm signal", "VERIFY correct operation of each alarm signal and, if monitored, alarm signalling equipment activation.", 0, "", 1, 1),
    ("1.14", "DSEP/DBEP strobe indicator", "INSPECT correct operation of each DSEP/DBEP strobe indicator where fitted.", 0, "", 1, 1),
    ("1.15", "System pressure gauge readings after alarm valve test", "RECORD pressure readings after alarm valve test and VERIFY they are within required ranges.", 1, "kPa", 1, 1),
    ("1.16", "Pump starting devices function test", "TEST automatic pump starting devices/pump operation and RECORD pump cut-in pressures.", 1, "kPa", 1, 1),
    ("1.17", "Manual pump start device function test", "TEST each manual pump starting device and pump operation in accordance with Section 3.", 0, "", 1, 1),
    ("1.18", "Water supply tanks (atmospheric or pressure)", "PERFORM routine service in accordance with Section 5.", 0, "", 1, 1),
    ("1.19", "Foam water sprinkler systems - foam concentrate", "CHECK concentrate level is correct and level indicator reads correctly.", 0, "", 1, 1),
]


def _get_or_create_monthly_frequency() -> str:
    name = frappe.db.get_value("FT Frequency", {"frequency_title": "Monthly"}, "name")
    if name:
        return name
    doc = frappe.get_doc({"doctype": "FT Frequency", "frequency_title": "Monthly"})
    doc.insert(ignore_permissions=True)
    return doc.name


def _get_or_create_standard() -> str:
    name = frappe.db.get_value("FT Standard", {"standard_code": STANDARD_CODE}, "name")
    if not name:
        doc = frappe.get_doc(
            {
                "doctype": "FT Standard",
                "standard_code": STANDARD_CODE,
                "standard_label": STANDARD_LABEL,
                "standard_version": STANDARD_VERSION,
                "standard_description": STANDARD_DESC,
            }
        )
        doc.insert(ignore_permissions=True)
        return doc.name

    frappe.db.set_value(
        "FT Standard",
        name,
        {
            "standard_label": STANDARD_LABEL,
            "standard_version": STANDARD_VERSION,
            "standard_description": STANDARD_DESC,
        },
        update_modified=False,
    )
    return name


def execute():
    freq_name = _get_or_create_monthly_frequency()
    std_name = _get_or_create_standard()

    suite_name = frappe.db.get_value("FT Test Suite", {"test_suite_code": SUITE_CODE}, "name")
    if suite_name:
        suite = frappe.get_doc("FT Test Suite", suite_name)
    else:
        suite = frappe.get_doc({"doctype": "FT Test Suite"})

    suite.test_suite_code = SUITE_CODE
    suite.test_suite_label = SUITE_LABEL
    suite.test_suite_standard = std_name
    suite.test_suite_frequency = freq_name
    suite.test_suite_table_ref = SUITE_TABLE_REF
    suite.test_suite_required_instrument = "None"
    suite.set("test_suite_items", [])

    for code, title, desc, requires_reading, uom, pass_required, defect_on_fail in ITEMS:
        suite.append(
            "test_suite_items",
            {
                "test_item_code": code,
                "test_item_description": f"{title}: {desc}",
                "test_item_requires_reading": int(requires_reading),
                "test_item_uom": uom or None,
                "test_item_pass_required": int(pass_required),
                "test_item_defect_on_fail": int(defect_on_fail),
            },
        )

    if suite.name:
        suite.save(ignore_permissions=True)
    else:
        suite.insert(ignore_permissions=True)

    frappe.db.commit()

