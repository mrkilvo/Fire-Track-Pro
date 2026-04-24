import frappe
from frappe import _

DOCTYPE = "FT Job"

STATUS_ALIASES = {
	"open": "Open",
	"in progress": "In Progress",
	"in_progress": "In Progress",
	"complete": "Completed",
	"completed": "Completed",
	"cancelled": "Cancelled",
	"canceled": "Cancelled",
}

_PRIORITY_CANON = {"Low", "Normal", "High", "Urgent"}
_STATUS_CANON = {"Open", "In Progress", "Completed", "Cancelled"}

_schema_cache: dict[str, str] | None = None
_opts_cache: dict[str, list[str]] | None = None


def _exists(doctype: str, name: str) -> bool:
	try:
		return bool(frappe.db.exists(doctype, name))
	except Exception:
		return False


def _fmt_dt(dt) -> str:
	if not dt:
		return ""
	try:
		return frappe.format_value(dt, {"fieldtype": "Datetime"}) or str(dt)
	except Exception:
		return str(dt)


def _resolve_schema() -> dict[str, str]:
	global _schema_cache
	if _schema_cache:
		return _schema_cache

	meta = frappe.get_meta(DOCTYPE)
	fields = meta.fields or []

	def find_link_to(options_name: str) -> str | None:
		for f in fields:
			if getattr(f, "fieldtype", "") == "Link" and getattr(f, "options", "") == options_name:
				return f.fieldname
		return None

	def find_by_pred(pred) -> str | None:
		for f in fields:
			if pred(f):
				return f.fieldname
		return None

	title = find_by_pred(
		lambda f: f.fieldtype in ("Data", "Small Text") and "title" in (f.fieldname or "").lower()
	)

	status = None
	for f in fields:
		if f.fieldtype == "Select":
			opts = [o.strip() for o in (getattr(f, "options", "") or "").split("\n") if o.strip()]
			canon_hits = sum(1 for o in opts if o in _STATUS_CANON)
			if canon_hits >= 2:
				status = f.fieldname
				break
	if not status:
		status = find_by_pred(lambda f: f.fieldtype == "Select" and "status" in (f.fieldname or "").lower())

	assignee = find_link_to("User")
	customer = find_link_to("Customer")
	property_ = find_link_to("FT Property")

	due_date = find_by_pred(
		lambda f: f.fieldtype in ("Date", "Datetime")
		and (("due" in (f.fieldname or "").lower()) or ("required" in (f.fieldname or "").lower()))
	)
	scheduled_start = find_by_pred(
		lambda f: f.fieldtype == "Datetime"
		and "scheduled" in (f.fieldname or "").lower()
		and "start" in (f.fieldname or "").lower()
	)
	scheduled_end = find_by_pred(
		lambda f: f.fieldtype == "Datetime"
		and "scheduled" in (f.fieldname or "").lower()
		and "end" in (f.fieldname or "").lower()
	)

	priority = None
	for f in fields:
		if f.fieldtype == "Select":
			opts = [o.strip() for o in (getattr(f, "options", "") or "").split("\n") if o.strip()]
			canon_hits = sum(1 for o in opts if o in _PRIORITY_CANON)
			if canon_hits >= 2 or "priority" in (f.fieldname or "").lower():
				priority = f.fieldname
				break

	notes = find_by_pred(
		lambda f: f.fieldtype in ("Small Text", "Long Text", "Text Editor")
		and ("note" in (f.fieldname or "").lower() or "remarks" in (f.fieldname or "").lower())
	)

	schema = {
		"title": title,
		"status": status,
		"assignee": assignee,
		"customer": customer,
		"property": property_,
		"due_date": due_date,
		"scheduled_start": scheduled_start,
		"scheduled_end": scheduled_end,
		"priority": priority,
		"notes": notes,
	}
	schema["name"] = "name"
	schema["modified"] = "modified"

	_schema_cache = schema
	return schema


def _get_select_options(fieldname: str) -> list[str]:
	global _opts_cache
	if _opts_cache is None:
		_opts_cache = {}
	if fieldname in _opts_cache:
		return _opts_cache[fieldname]
	meta = frappe.get_meta(DOCTYPE)
	f = next((x for x in meta.fields if x.fieldname == fieldname), None)
	if not f or f.fieldtype != "Select":
		_opts_cache[fieldname] = []
		return []
	opts = [o.strip() for o in (getattr(f, "options", "") or "").split("\n") if o.strip()]
	_opts_cache[fieldname] = opts
	return opts


def _safe_fields(requested: list[str]) -> list[str]:
	meta = frappe.get_meta(DOCTYPE)
	colset = {c.fieldname for c in meta.fields}
	out = []
	for c in requested:
		if c in ("name", "modified") or c in colset or frappe.db.has_column(DOCTYPE, c):
			out.append(c)
	if "name" not in out:
		out.append("name")
	if "modified" not in out:
		out.append("modified")
	return out


def _coerce_status(v: str | None) -> str | None:
	if not v:
		return None
	v = STATUS_ALIASES.get(v.strip().lower(), v.strip())
	opts = _get_select_options(_resolve_schema().get("status") or "")
	valid = set(opts) if opts else _STATUS_CANON
	if v and v not in valid:
		frappe.throw(_("Invalid status: {0}").format(v))
	return v


def _coerce_priority(v: str | None) -> str | None:
	if not v:
		return None
	v = v.strip().capitalize()
	opts = _get_select_options(_resolve_schema().get("priority") or "")
	valid = set(opts) if opts else _PRIORITY_CANON
	if v and v not in valid:
		frappe.throw(_("Invalid priority: {0}").format(v))
	return v


def _apply_fields(doc, payload: dict):
	sch = _resolve_schema()

	if "title" in payload and sch.get("title"):
		doc.set(sch["title"], payload.get("title"))
	if "assignee" in payload and sch.get("assignee"):
		doc.set(sch["assignee"], payload.get("assignee"))
	if "status" in payload and sch.get("status"):
		doc.set(sch["status"], _coerce_status(payload.get("status")))
	if "due_date" in payload and sch.get("due_date"):
		doc.set(sch["due_date"], payload.get("due_date"))
	if "priority" in payload and sch.get("priority"):
		doc.set(sch["priority"], _coerce_priority(payload.get("priority")))
	if "notes" in payload and sch.get("notes"):
		doc.set(sch["notes"], payload.get("notes"))
	if "customer" in payload and sch.get("customer"):
		doc.set(sch["customer"], payload.get("customer"))
	if "property" in payload and sch.get("property"):
		doc.set(sch["property"], payload.get("property"))
	if "scheduled_start" in payload and sch.get("scheduled_start"):
		doc.set(sch["scheduled_start"], payload.get("scheduled_start"))
	if "scheduled_end" in payload and sch.get("scheduled_end"):
		doc.set(sch["scheduled_end"], payload.get("scheduled_end"))


def _pack_job(doc) -> dict:
	sch = _resolve_schema()
	return {
		"name": doc.name,
		"job_title": doc.get(sch.get("title")),
		"job_property": doc.get(sch.get("property")),
		"job_status": doc.get(sch.get("status")),
		"assignee": doc.get(sch.get("assignee")),
		"priority": doc.get(sch.get("priority")),
		"due_date": doc.get(sch.get("due_date")),
		"scheduled_start": doc.get(sch.get("scheduled_start")),
		"scheduled_end": doc.get(sch.get("scheduled_end")),
		"modified": doc.modified,
	}


def _emit_job_event(doc, kind: str):
	evt = "ft_job:new" if kind == "new" else "ft_job:update"
	frappe.publish_realtime(
		event=evt,
		message=_pack_job(doc),
		doctype=DOCTYPE,
		docname=doc.name,
		after_commit=True,
	)


@frappe.whitelist()
def list_jobs(q: str | None = None, limit: int = 100, start: int = 0):
	user = frappe.session.user
	if user in ("Guest", None):
		frappe.throw(_("Login required"))

	sch = _resolve_schema()
	requested_fields = [
		sch.get("name", "name"),
		sch.get("modified", "modified"),
		sch.get("title"),
		sch.get("status"),
		sch.get("assignee"),
		sch.get("due_date"),
		sch.get("priority"),
	]
	fields = _safe_fields([c for c in requested_fields if c])

	or_filters = None
	if q:
		like = f"%{q}%"
		searchable = [
			c
			for c in [sch.get("name", "name"), sch.get("title"), sch.get("assignee"), sch.get("status")]
			if c
		]
		or_filters = [[DOCTYPE, col, "like", like] for col in searchable]

	rows = frappe.db.get_list(
		DOCTYPE,
		fields=fields,
		or_filters=or_filters,
		order_by="modified desc",
		limit=limit,
		start=start,
		ignore_permissions=True,
		as_list=False,
	)

	return [
		{
			"id": r.get("name"),
			"title": r.get(sch.get("title")),
			"assignee": r.get(sch.get("assignee")),
			"status": r.get(sch.get("status")),
			"updated": _fmt_dt(r.get("modified")),
			"priority": r.get(sch.get("priority")),
		}
		for r in rows
	]


@frappe.whitelist()
def get_job(name: str):
	user = frappe.session.user
	if user in ("Guest", None):
		frappe.throw(_("Login required"))
	if not _exists(DOCTYPE, name):
		frappe.throw(_("Job not found"))

	sch = _resolve_schema()
	requested_fields = [
		sch.get("name", "name"),
		sch.get("modified", "modified"),
		sch.get("title"),
		sch.get("status"),
		sch.get("assignee"),
		sch.get("customer"),
		sch.get("property"),
		sch.get("due_date"),
		sch.get("scheduled_start"),
		sch.get("scheduled_end"),
		sch.get("priority"),
		sch.get("notes"),
	]
	fields = _safe_fields([c for c in requested_fields if c])

	row = frappe.db.get_value(DOCTYPE, name, fields, as_dict=True) or {}

	return {
		"id": row.get("name"),
		"title": row.get(sch.get("title")),
		"assignee": row.get(sch.get("assignee")),
		"status": row.get(sch.get("status")) or "Open",
		"customer": row.get(sch.get("customer")),
		"property": row.get(sch.get("property")),
		"due_date": row.get(sch.get("due_date")),
		"scheduled_start": row.get(sch.get("scheduled_start")),
		"scheduled_end": row.get(sch.get("scheduled_end")),
		"priority": row.get(sch.get("priority")) or "Normal",
		"notes": row.get(sch.get("notes")),
		"updated": _fmt_dt(row.get("modified")),
	}


@frappe.whitelist()
def create_job(**kwargs):
	user = frappe.session.user
	if user in ("Guest", None):
		frappe.throw(_("Login required"))
	doc = frappe.new_doc(DOCTYPE)
	_apply_fields(doc, kwargs or {})
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	_emit_job_event(doc, "new")
	return {"name": doc.name}


@frappe.whitelist()
def update_job(**kwargs):
	user = frappe.session.user
	if user in ("Guest", None):
		frappe.throw(_("Login required"))
	name = kwargs.get("name")
	if not name:
		frappe.throw(_("Missing required field: name"))
	if not _exists(DOCTYPE, name):
		frappe.throw(_("Job not found"))

	doc = frappe.get_doc(DOCTYPE, name)
	_apply_fields(doc, kwargs or {})
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	_emit_job_event(doc, "update")
	return {"name": doc.name}


@frappe.whitelist()
def delete_job(name: str):
	user = frappe.session.user
	if user in ("Guest", None):
		frappe.throw(_("Login required"))
	if not _exists(DOCTYPE, name):
		frappe.throw(_("Job not found"))
	frappe.delete_doc(DOCTYPE, name, ignore_permissions=True, force=1)
	frappe.db.commit()
	return {"ok": True}


@frappe.whitelist()
def jobs_count():
	return {"count": frappe.db.count(DOCTYPE)}


@frappe.whitelist()
def get_schema():
	"""
	Returns the resolved fieldname mapping + select options so the
	frontend can render the correct dropdowns.
	"""
	sch = _resolve_schema()
	status_opts = _get_select_options(sch.get("status") or "")
	priority_opts = _get_select_options(sch.get("priority") or "")
	return {"fields": sch, "status_options": status_opts, "priority_options": priority_opts}


@frappe.whitelist()
def get_related(name: str):
	user = frappe.session.user
	if user in ("Guest", None):
		frappe.throw(_("Login required"))
	if not frappe.db.exists("FT Job", name):
		frappe.throw(_("Job not found"))

	meta = frappe.get_meta("FT Job")
	fields = meta.fields or []

	CANDIDATE_QUOTES = {"Quotation", "Sales Order", "FT Quote", "FT Quotation", "FT Sales Order"}
	CANDIDATE_INVS = {"Sales Invoice", "FT Invoice", "FT Sales Invoice"}

	def find_link_to(candidates: set[str]):
		for f in fields:
			if getattr(f, "fieldtype", "") == "Link" and getattr(f, "options", "") in candidates:
				return f.fieldname, f.options
		return None, None

	quote_link_field, quote_dt = find_link_to(CANDIDATE_QUOTES)
	inv_link_field, inv_dt = find_link_to(CANDIDATE_INVS)

	row = (
		frappe.db.get_value(
			"FT Job",
			name,
			[c for c in ["name", quote_link_field, inv_link_field] if c],
			as_dict=True,
		)
		or {}
	)

	quote_name = row.get(quote_link_field) if quote_link_field else None
	inv_name = row.get(inv_link_field) if inv_link_field else None

	def pull_items(parent_dt: str, parent_name: str):
		if not parent_dt or not parent_name or not frappe.db.exists(parent_dt, parent_name):
			return []
		parent_meta = frappe.get_meta(parent_dt)
		tbl = None
		for f in parent_meta.fields or []:
			if f.fieldtype == "Table" and (
				"item" in (f.fieldname or "").lower() or (f.options or "").lower().endswith(" item")
			):
				tbl = f
				break
		if not tbl:
			return []
		cols = ["name", "idx"]
		for want in ["item_code", "item_name", "description", "qty", "uom", "rate", "amount"]:
			if frappe.db.has_column(tbl.options, want):
				cols.append(want)
		children = frappe.get_all(
			tbl.options,
			filters={"parent": parent_name, "parenttype": parent_dt},
			fields=cols,
			order_by="idx asc",
		)
		out = []
		for c in children:
			out.append(
				{
					"idx": c.get("idx"),
					"item_code": c.get("item_code") or "",
					"item_name": c.get("item_name") or "",
					"description": c.get("description") or "",
					"qty": c.get("qty"),
					"uom": c.get("uom") or "",
					"rate": c.get("rate"),
					"amount": c.get("amount"),
				}
			)
		return out

	quote_items = pull_items(quote_dt, quote_name)
	inv_items = pull_items(inv_dt, inv_name)

	return {
		"quote_field": quote_link_field,
		"quote_doctype": quote_dt,
		"quote_name": quote_name,
		"quote_items": quote_items,
		"invoice_field": inv_link_field,
		"invoice_doctype": inv_dt,
		"invoice_name": inv_name,
		"invoice_items": inv_items,
	}


@frappe.whitelist()
def attach_related(name: str, kind: str, docname: str):
	"""
	Attach an existing Quotation/Sales Invoice (or FT equivalents) to this job by name.
	kind: 'quote' | 'invoice'
	"""
	user = frappe.session.user
	if user in ("Guest", None):
		frappe.throw(_("Login required"))
	if not frappe.db.exists("FT Job", name):
		frappe.throw(_("Job not found"))

	rel = get_related(name)
	rel = rel.get("message", rel)

	if kind == "quote":
		fieldname = rel.get("quote_field")
		target_dt = rel.get("quote_doctype")
	elif kind == "invoice":
		fieldname = rel.get("invoice_field")
		target_dt = rel.get("invoice_doctype")
	else:
		frappe.throw(_("Invalid kind"))

	if not fieldname or not target_dt:
		frappe.throw(_("No link field on FT Job for {0}. Add a Link field to your Job doctype.").format(kind))

	if not frappe.db.exists(target_dt, docname):
		frappe.throw(_("Document {0} {1} not found").format(target_dt, docname))

	doc = frappe.get_doc("FT Job", name)
	doc.set(fieldname, docname)
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"ok": True, "name": name, "linked": {kind: docname}}


# ---------------------------------------------------------------------------
# Assigned-to-me list: Lead User OR Job Crew (via FT Technician mapping)
# ---------------------------------------------------------------------------
@frappe.whitelist()
def list_jobs_assigned(limit: int = 500, active_only: int = 0):
	"""
	Return jobs where the current user is:
	  - Lead user (FT Job.job_lead_user == user), or
	  - In FT Job Crew (job_crew_technician maps to my FT Technician), or
	  - Scheduled via FT Schedule (schedule_technician == user)  <-- new

	If active_only=1 and a status Select exists, filter to a broader active set.
	"""
	user = frappe.session.user
	if user in ("Guest", None):
		frappe.throw(_("Login required"))

	sch = _resolve_schema()
	fields = _safe_fields(
		[
			sch.get("name", "name"),
			sch.get("modified", "modified"),
			sch.get("title"),
			sch.get("status"),
			sch.get("property"),
			sch.get("due_date"),
			sch.get("scheduled_start"),
			sch.get("scheduled_end"),
			sch.get("priority"),
		]
	)

	# A) Lead jobs
	lead_field = "job_lead_user" if frappe.db.has_column(DOCTYPE, "job_lead_user") else None
	if not lead_field:
		meta = frappe.get_meta(DOCTYPE)
		for f in meta.fields or []:
			if (
				getattr(f, "fieldtype", "") in ("Link", "Data")
				and "lead" in (f.fieldname or "").lower()
				and "user" in (f.fieldname or "").lower()
			):
				lead_field = f.fieldname
				break
	lead_names = set()
	if lead_field:
		for r in frappe.get_all(DOCTYPE, filters={lead_field: user}, fields=["name"], limit=limit):
			lead_names.add(r["name"])

	# B) Crew jobs (via FT Technician)
	crew_names = set()
	tech_name = frappe.db.get_value("FT Technician", {"technician_user": user}, "name")
	if tech_name and frappe.db.exists("DocType", "FT Job Crew"):
		for r in frappe.get_all(
			"FT Job Crew", filters={"job_crew_technician": tech_name}, fields=["parent"], limit=10000
		):
			crew_names.add(r["parent"])

	# C) Scheduled jobs (via FT Schedule)
	sched_names = set()
	if frappe.db.exists("DocType", "FT Schedule"):
		for r in frappe.get_all(
			"FT Schedule", filters={"schedule_technician": user}, fields=["schedule_job"], limit=10000
		):
			if r.get("schedule_job"):
				sched_names.add(r["schedule_job"])

	job_names = list(lead_names | crew_names | sched_names)
	if not job_names:
		return []

	filters = [[DOCTYPE, "name", "in", job_names]]

	# Broader active statuses, optional
	status_field = sch.get("status")
	if active_only and status_field and _get_select_options(status_field):
		filters.append(
			[
				DOCTYPE,
				status_field,
				"in",
				["Draft", "Planned", "Scheduled", "In Progress", "Complete", "Office Review"],
			]
		)

	rows = frappe.db.get_list(
		DOCTYPE,
		fields=fields,
		filters=filters,
		order_by=f"{sch.get('scheduled_start') or 'modified'} asc, modified desc",
		limit=limit,
		ignore_permissions=True,
		as_list=False,
	)

	out = []
	for r in rows:
		out.append(
			{
				"name": r.get("name"),
				"job_title": r.get(sch.get("title")),
				"job_property": r.get(sch.get("property")),
				"job_status": r.get(sch.get("status")),
				"job_scheduled_start": r.get(sch.get("scheduled_start")),
				"job_scheduled_end": r.get(sch.get("scheduled_end")),
				"job_due_date": r.get(sch.get("due_date")),
				"job_priority": r.get(sch.get("priority")),
				"updated": _fmt_dt(r.get("modified")),
			}
		)
	return out
