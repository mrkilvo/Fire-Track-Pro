# firtrackpro/firtrackpro/www/portal/tasks/scheduler/index.py
from __future__ import annotations

import frappe


def get_context(context):
	# Require login
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login"
		raise frappe.Redirect

	context.no_cache = 1

	# Optional: read Scheduler license key from site_config.json.
	# Set it with:
	# bench --site your.site set-config fullcalendar_scheduler_license_key "YOUR-LICENSE-KEY"
	context.fc_license_key = (
		frappe.conf.get("fullcalendar_scheduler_license_key") or "GPL-My-Project-Is-Open-Source"
	)

	# Optional: expose script URLs to the template (if you want to interpolate them)
	context.fc_urls = {
		"scheduler_local": "/assets/firtrackpro/js/vendor/fullcalendar-scheduler/index.global.min.js",
		"scheduler_cdn": "https://cdn.jsdelivr.net/npm/fullcalendar-scheduler@6.1.19/index.global.min.js",
		"standard_local": "/assets/firtrackpro/js/vendor/fullcalendar/index.global.min.js",
		"standard_cdn": "https://cdn.jsdelivr.net/npm/fullcalendar@6.1.19/index.global.min.js",
	}

	# Demo tasks for sidebar
	context.tasks = [
		{
			"status": "READY",
			"type": "CALLOUT",
			"code": "T-00304",
			"title": "Site attendance to investigate defect relating to overheating pump.",
			"site": "915 Collins Street, Docklands",
			"client": "Entire Service & Maintenance Pty Ltd",
			"duration": "2:00",
		},
		{
			"status": "READY",
			"type": "I&T",
			"code": "T-00303",
			"title": "PM2025/08 Servicing - Sprinkler",
			"site": "56 Elliot St Reservoir VIC 3073",
			"client": "Firewatch Safety Results Group",
			"duration": "4:00",
		},
		{
			"status": "IN PROGRESS",
			"type": "MAINTENANCE",
			"code": "T-00302",
			"title": "Monthly Alarm System Test",
			"site": "100 Swanston St, Melbourne",
			"client": "ACME Holdings Pty Ltd",
			"duration": "1:00",
		},
	]

	# Demo resources (technicians) — note team & region for grouping
	context.resources = [
		{
			"id": "tech1",
			"title": "Alice Johnson — FPA-123",
			"color": "#93c5fd",
			"team": "North",
			"region": "VIC",
		},
		{
			"id": "tech2",
			"title": "Bob Singh — FPA-456",
			"color": "#86efac",
			"team": "South",
			"region": "VIC",
		},
		{
			"id": "tech3",
			"title": "Cara Lee — FPA-789",
			"color": "#fca5a5",
			"team": "East",
			"region": "NSW",
		},
		{
			"id": "tech4",
			"title": "Diego Martinez — FPA-321",
			"color": "#f9a8d4",
			"team": "North",
			"region": "NSW",
		},
		{
			"id": "tech5",
			"title": "Eve Chen — FPA-654",
			"color": "#fdba74",
			"team": "South",
			"region": "VIC",
		},
		{
			"id": "tech6",
			"title": "Finn O'Neil — FPA-987",
			"color": "#c4b5fd",
			"team": "East",
			"region": "QLD",
		},
		{
			"id": "tech7",
			"title": "Gina Rossi — FPA-111",
			"color": "#6ee7b7",
			"team": "West",
			"region": "WA",
		},
		{
			"id": "tech8",
			"title": "Harry King — FPA-222",
			"color": "#93c5fd",
			"team": "West",
			"region": "WA",
		},
		{
			"id": "tech9",
			"title": "Isla Patel — FPA-333",
			"color": "#86efac",
			"team": "North",
			"region": "VIC",
		},
		{
			"id": "tech10",
			"title": "Jack Wong — FPA-444",
			"color": "#fca5a5",
			"team": "South",
			"region": "VIC",
		},
	]

	# Demo events
	context.events = [
		{
			"id": 1,
			"title": "Overheating pump defect",
			"start": "2025-08-04T09:00:00",
			"end": "2025-08-04T11:00:00",
			"resourceId": "tech1",
		},
		{
			"id": 2,
			"title": "Sprinkler PM2025/08",
			"start": "2025-08-05T12:00:00",
			"end": "2025-08-05T16:00:00",
			"resourceId": "tech2",
		},
		{
			"id": 3,
			"title": "Alarm System Test",
			"start": "2025-08-07T10:00:00",
			"end": "2025-08-07T11:00:00",
			"resourceId": "tech3",
		},
	]

	return context
