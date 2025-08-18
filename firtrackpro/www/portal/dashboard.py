import frappe
from frappe import _
from frappe.utils import nowdate
from frappe.www.utils import get_home_page


def get_context(context):
    user = frappe.session.user
    user_roles = frappe.get_roles(user)

    # Example data fetching (replace with real queries)
    context.jobs_count = frappe.db.count(
        "Job", {"owner": user, "creation": [">=", nowdate()]}
    )
    context.open_tasks = frappe.db.count("Task", {"status": "Open", "owner": user})
    context.upcoming_appointments = frappe.db.count(
        "Appointment", {"owner": user, "date": [">=", nowdate()]}
    )
    context.incidents = frappe.db.count("Incident", {"owner": user, "status": "Open"})

    # Recent activity (replace with real queries)
    context.recent_activity = [
        {"icon": "briefcase", "text": _("Created Job #123"), "time": "2h ago"},
        {"icon": "list", "text": _("Completed Task #456"), "time": "4h ago"},
        {"icon": "alert-circle", "text": _("Logged Incident #789"), "time": "1d ago"},
    ]
    # Upcoming events (replace with real queries)
    context.upcoming_events = [
        {"title": _("Appointment with Client X"), "date": "2025-08-05"},
        {"title": _("Task Review"), "date": "2025-08-06"},
    ]
    # Announcements (replace with real queries)
    context.announcements = [
        _("System maintenance on 2025-08-10."),
        _("New feature: Bulk Operations!"),
    ]
    context.user_roles = user_roles
    return context
