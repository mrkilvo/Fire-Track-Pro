import frappe

TASK_SETUP_DEFS = [
    {
        "code": "FT-LABOUR",
        "label": "Labour",
        "frequency": "Monthly",
        "items": [
            ("1", "Labour (Hour): Record time worked for this service activity.", 1, "hr"),
        ],
    },
    {
        "code": "FT-FLOW-TEST",
        "label": "Flow Test",
        "frequency": "Monthly",
        "items": [
            ("1", "Static pressure: Record pre-test static pressure reading.", 1, "kPa"),
            ("2", "Residual pressure: Record residual pressure under flow.", 1, "kPa"),
            ("3", "Flow rate: Record measured flow rate.", 1, "L/min"),
        ],
    },
]

STANDARD_ITEM_DEFS = [
    {"item_code": "ATTENDANCE-FEE", "item_name": "Attendance Fee", "description": "Standard attendance fee.", "stock_uom": "Nos"},
    {"item_code": "CALLOUT-FEE", "item_name": "Callout Fee", "description": "Standard callout fee.", "stock_uom": "Nos"},
    {"item_code": "LABOUR-HOUR", "item_name": "Labour (Hour)", "description": "Standard labour charged per hour.", "stock_uom": "Hour"},
    {"item_code": "FLOW-TEST-SERVICE", "item_name": "Flow Test Service", "description": "Standard flow test service line item.", "stock_uom": "Nos"},
    {"item_code": "AFTER-HOURS-LABOUR", "item_name": "After Hours Labour", "description": "Standard after-hours labour charge.", "stock_uom": "Hour"},
    {"item_code": "TRAVEL-FEE", "item_name": "Travel Fee", "description": "Standard travel fee.", "stock_uom": "Nos"},
]


def _ensure_uom(uom_name: str) -> None:
    if frappe.db.exists("UOM", uom_name):
        return
    doc = frappe.get_doc({"doctype": "UOM", "uom_name": uom_name, "enabled": 1})
    doc.insert(ignore_permissions=True)


def _ensure_item(item_def: dict) -> None:
    item_code = item_def["item_code"]
    existing = frappe.db.get_value("Item", {"item_code": item_code}, "name")
    if existing:
        doc = frappe.get_doc("Item", existing)
    else:
        doc = frappe.new_doc("Item")
        doc.item_code = item_code

    doc.item_name = item_def["item_name"]
    doc.description = item_def.get("description")
    doc.item_group = frappe.db.get_single_value("Stock Settings", "item_group") or "All Item Groups"
    doc.stock_uom = item_def.get("stock_uom") or "Nos"
    doc.is_stock_item = 0
    doc.disabled = 0
    doc.save(ignore_permissions=True)


def _ensure_task_setup(defn: dict) -> None:
    code = defn["code"]
    suite_name = frappe.db.get_value("FT Test Suite", {"test_suite_code": code}, "name")
    suite = frappe.get_doc("FT Test Suite", suite_name) if suite_name else frappe.new_doc("FT Test Suite")

    freq_name = frappe.db.get_value("FT Frequency", {"frequency_title": defn["frequency"]}, "name")
    if not freq_name:
        freq = frappe.get_doc({"doctype": "FT Frequency", "frequency_title": defn["frequency"]})
        freq.insert(ignore_permissions=True)
        freq_name = freq.name

    suite.test_suite_code = code
    suite.test_suite_label = defn["label"]
    suite.test_suite_frequency = freq_name
    suite.test_suite_required_instrument = "None"
    suite.test_suite_table_ref = "Custom"
    suite.set("test_suite_items", [])

    for item_code, description, requires_reading, uom in defn["items"]:
        suite.append(
            "test_suite_items",
            {
                "test_item_code": item_code,
                "test_item_description": description,
                "test_item_requires_reading": int(requires_reading),
                "test_item_uom": uom,
                "test_item_pass_required": 1,
                "test_item_defect_on_fail": 1,
            },
        )

    if suite.name:
        suite.save(ignore_permissions=True)
    else:
        suite.insert(ignore_permissions=True)


def execute():
    _ensure_uom("Hour")
    _ensure_uom("hr")
    for task_setup in TASK_SETUP_DEFS:
        _ensure_task_setup(task_setup)
    for item_def in STANDARD_ITEM_DEFS:
        _ensure_item(item_def)
    frappe.db.commit()


@frappe.whitelist()
def verify_seed():
    suites = frappe.get_all(
        "FT Test Suite",
        filters={"test_suite_code": ["in", ["FT-LABOUR", "FT-FLOW-TEST"]]},
        fields=["name", "test_suite_code", "test_suite_label"],
        limit=20,
    )
    items = frappe.get_all(
        "Item",
        filters={"item_code": ["in", ["ATTENDANCE-FEE", "CALLOUT-FEE", "LABOUR-HOUR", "FLOW-TEST-SERVICE", "AFTER-HOURS-LABOUR", "TRAVEL-FEE"]]},
        fields=["name", "item_code", "item_name", "stock_uom"],
        limit=50,
    )
    return {"suites": suites, "items": items}