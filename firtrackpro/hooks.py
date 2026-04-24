# apps/firtrackpro/firtrackpro/hooks.py

app_name = "firtrackpro"
app_title = "Fire Track Pro"
app_publisher = "SJK"
app_description = "Fire Support System"
app_email = "freefallkilvo@yahoo.com.au"
app_license = "mit"

app_include_css = "assets/firtrackpro/css/brand.css"


website_route_rules = [
	{"from_route": "/", "to_route": "index"},
	{"from_route": "/signup", "to_route": "index"},
	{"from_route": "/portal", "to_route": "portal"},
	{"from_route": "/portal/<path:app_path>", "to_route": "portal"},
	{"from_route": "/client", "to_route": "client"},
	{"from_route": "/client/<path:app_path>", "to_route": "client"},
]


doc_events = {
	"FT Job": {
		"after_insert": "firtrackpro.events.jobs.emit_job_inserted",
		"on_update": "firtrackpro.events.jobs.emit_job_updated",
		"on_trash": "firtrackpro.events.jobs.emit_job_deleted",
		"after_delete": "firtrackpro.events.jobs.emit_job_deleted",  # optional safety
	},
	"FT Schedule": {
		"after_insert": "firtrackpro.events.jobs.emit_schedule_inserted",
		"on_update": "firtrackpro.events.jobs.emit_schedule_updated",
	},
}
