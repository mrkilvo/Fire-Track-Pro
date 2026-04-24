import frappe
from frappe.utils import get_datetime


def _safe_get_all(doctype, **kwargs):
	try:
		return frappe.get_all(doctype, **kwargs)
	except frappe.DoesNotExistError:
		return []
	except Exception:
		try:
			frappe.log_error(
				frappe.get_traceback(),
				f"Scheduler safe_get_all error: {doctype}",
			)
		except Exception:
			pass
		return []


def _get_technicians():
	technicians = []

	tech_rows = _safe_get_all(
		"FT Technician",
		fields=["name", "technician_user"],
		order_by="name asc",
	)

	if tech_rows:
		user_ids = [t["technician_user"] for t in tech_rows if t.get("technician_user")]
		user_map = {}
		if user_ids:
			for u in _safe_get_all(
				"User",
				filters={"name": ["in", user_ids]},
				fields=["name", "full_name", "email"],
			):
				user_map[u["name"]] = u

		for t in tech_rows:
			user_id = t.get("technician_user")
			user = user_map.get(user_id) if user_id else None
			label = None
			if user:
				label = user.get("full_name") or user.get("email") or user.get("name")
			technicians.append(
				{
					"id": user_id or t["name"],
					"name": label or t["name"],
					"color": None,
				}
			)
		return technicians

	users = _safe_get_all(
		"User",
		filters={"enabled": 1, "user_type": "System User"},
		fields=["name", "full_name", "email"],
		order_by="full_name asc",
	)
	for u in users:
		label = u.get("full_name") or u.get("email") or u.get("name")
		technicians.append(
			{
				"id": u["name"],
				"name": label,
				"color": None,
			}
		)
	return technicians


def _get_jobs_with_schedule():
	jobs = _safe_get_all(
		"FT Job",
		fields=[
			"name",
			"job_title",
			"job_status",
			"job_property",
			"job_scheduled_start",
			"job_scheduled_end",
			"job_lead_user",
			"job_required_date",
		],
		order_by="modified desc",
		limit_page_length=500,
	)
	if not jobs:
		return []

	job_ids = [j["name"] for j in jobs]
	property_ids = list({j["job_property"] for j in jobs if j.get("job_property")})

	schedules = _safe_get_all(
		"FT Schedule",
		filters={"schedule_job": ["in", job_ids]},
		fields=[
			"name",
			"schedule_job",
			"schedule_property",
			"schedule_required_date",
			"schedule_scheduled_start",
			"schedule_scheduled_end",
			"schedule_technician",
			"schedule_bucket",
			"schedule_ready",
		],
		limit_page_length=1000,
	)

	schedule_by_job = {}
	for s in schedules:
		key = s.get("schedule_job")
		if key and key not in schedule_by_job:
			schedule_by_job[key] = s

	property_name_by_id = {}
	if property_ids:
		for p in _safe_get_all(
			"FT Property",
			filters={"name": ["in", property_ids]},
			fields=["name", "property_name"],
		):
			property_name_by_id[p["name"]] = p.get("property_name") or p["name"]

	result = []
	for j in jobs:
		sched = schedule_by_job.get(j["name"])

		if sched:
			scheduled_start = sched.get("schedule_scheduled_start")
			scheduled_end = sched.get("schedule_scheduled_end")
			technician_id = sched.get("schedule_technician")
			bucket = sched.get("schedule_bucket") or "unassigned"
			required_date = sched.get("schedule_required_date") or j.get("job_required_date")
		else:
			scheduled_start = j.get("job_scheduled_start")
			scheduled_end = j.get("job_scheduled_end")
			technician_id = j.get("job_lead_user")
			bucket = "unassigned"
			required_date = j.get("job_required_date")

		property_id = j.get("job_property")
		property_name = property_name_by_id.get(property_id) if property_id else None

		duration_minutes = 90
		if scheduled_start and scheduled_end:
			try:
				delta = scheduled_end - scheduled_start
				if delta:
					duration_minutes = int(delta.total_seconds() // 60)
			except Exception:
				duration_minutes = 90

		raw_status = (j.get("job_status") or "").strip() or "Planned"
		if scheduled_start and scheduled_end:
			scheduler_status = "Scheduled"
		else:
			scheduler_status = "Planned"

		if bucket == "urgent":
			priority = "urgent"
		else:
			priority = "normal"

		result.append(
			{
				"id": j["name"],
				"title": j.get("job_title") or j["name"],
				"status": raw_status,  # real FT Job status: Planned / Finalised / Closed / etc.
				"scheduler_status": scheduler_status,  # Planned / Scheduled for the calendar logic
				"property_name": property_name,
				"technician_id": technician_id,
				"scheduled_start": scheduled_start,
				"scheduled_end": scheduled_end,
				"required_date": required_date,
				"duration_minutes": duration_minutes,
				"priority": priority,
			}
		)

	return result


@frappe.whitelist()
def get_schedule():
	technicians = _get_technicians()
	jobs = _get_jobs_with_schedule()
	return {
		"technicians": technicians,
		"jobs": jobs,
	}


@frappe.whitelist()
def update_job_schedule(job_id, start=None, end=None, technician_id=None, bucket=None):
	if not job_id:
		frappe.throw("job_id is required")

	if isinstance(start, str) and start.strip() == "":
		start = None
	if isinstance(end, str) and end.strip() == "":
		end = None

	start_dt = get_datetime(start) if start else None
	end_dt = get_datetime(end) if end else None

	sched_name = frappe.db.get_value(
		"FT Schedule",
		{"schedule_job": job_id},
		"name",
	)

	if not start_dt and not end_dt:
		if sched_name:
			try:
				frappe.delete_doc("FT Schedule", sched_name)
			except Exception:
				try:
					frappe.log_error(
						frappe.get_traceback(),
						"Scheduler: failed to delete FT Schedule on unschedule",
					)
				except Exception:
					pass

		try:
			job = frappe.get_doc("FT Job", job_id)
			job.job_scheduled_start = None
			job.job_scheduled_end = None
			job.job_lead_user = None if technician_id is not None else job.job_lead_user
			job.save()
		except Exception:
			try:
				frappe.log_error(
					frappe.get_traceback(),
					f"Scheduler: failed to clear schedule on FT Job {job_id}",
				)
			except Exception:
				pass

		return {"status": "ok", "job_id": job_id, "schedule_id": None}

	if sched_name:
		sched = frappe.get_doc("FT Schedule", sched_name)
	else:
		try:
			job = frappe.get_doc("FT Job", job_id)
		except Exception:
			try:
				frappe.log_error(
					frappe.get_traceback(),
					f"Scheduler: failed to load FT Job {job_id}",
				)
			except Exception:
				pass
			frappe.throw("Unable to update schedule for this job")

		sched = frappe.get_doc(
			{
				"doctype": "FT Schedule",
				"schedule_job": job.name,
				"schedule_property": getattr(job, "job_property", None),
			}
		)

	if start_dt:
		sched.schedule_scheduled_start = start_dt
	if end_dt:
		sched.schedule_scheduled_end = end_dt
	if technician_id is not None:
		sched.schedule_technician = technician_id
	if bucket:
		sched.schedule_bucket = bucket

	try:
		if sched.get("name"):
			sched.save()
		else:
			sched.insert()
	except Exception:
		try:
			frappe.log_error(
				frappe.get_traceback(),
				f"Scheduler: failed to save FT Schedule for job {job_id}",
			)
		except Exception:
			pass
		frappe.throw("Unable to save schedule")

	try:
		job = frappe.get_doc("FT Job", job_id)
		job.job_scheduled_start = sched.schedule_scheduled_start
		job.job_scheduled_end = sched.schedule_scheduled_end
		if technician_id is not None:
			job.job_lead_user = technician_id
		job.save()
	except Exception:
		try:
			frappe.log_error(
				frappe.get_traceback(),
				f"Scheduler: failed to update FT Job scheduled fields {job_id}",
			)
		except Exception:
			pass

	return {
		"status": "ok",
		"job_id": job_id,
		"schedule_id": sched.name,
		"scheduled_start": sched.schedule_scheduled_start,
		"scheduled_end": sched.schedule_scheduled_end,
		"technician_id": sched.schedule_technician,
		"bucket": sched.schedule_bucket,
	}
