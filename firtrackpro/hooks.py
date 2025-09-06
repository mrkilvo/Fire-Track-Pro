# apps/firtrackpro/firtrackpro/hooks.py

app_name = "firtrackpro"
app_title = "Fire Track Pro"
app_publisher = "SJK"
app_description = "Fire Support System"
app_email = "freefallkilvo@yahoo.com.au"
app_license = "mit"

# Brand CSS (keep)
app_include_css = "assets/firtrackpro/css/brand.css"

# ── Realtime emitters ─────────────────────────────────────────────────────────

# Use commit-safe events:
# - after_insert: new doc created
# - on_update: doc saved (we'll still publish after_commit=True)
# - after_delete: doc removed
doc_events = {
    "FT Job": {
        "after_insert": "firtrackpro.events.jobs.emit_job_inserted",
        "on_update": "firtrackpro.events.jobs.emit_job_updated",
        "after_delete": "firtrackpro.events.jobs.emit_job_deleted",
    }
}