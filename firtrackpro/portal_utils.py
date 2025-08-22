import hashlib
from urllib.parse import quote

import frappe
from frappe.utils import get_fullname, get_url


def _redirect_to_login(target: str):
    frappe.local.response["type"] = "redirect"
    frappe.local.response["location"] = f"/login?redirect-to={quote(target)}"


def _gravatar(email: str, size: int = 64) -> str:
    h = hashlib.md5((email or "").strip().lower().encode("utf-8")).hexdigest()
    # "mp" = silhouette fallback
    return f"https://www.gravatar.com/avatar/{h}?s={size}&d=mp"


def _best_user_image_url(user: str) -> str:
    """Absolute URL for user's avatar with fallbacks."""
    path = frappe.db.get_value("User", user, "user_image")
    if path:
        try:
            return get_url(path)  # handles /files and /private/files
        except Exception:
            pass
    return _gravatar(user, 64) or "/assets/frappe/images/avatar.svg"


def build_portal_context(
    context,
    *,
    page_h1: str = "Untitled",
    messages_url: str = "/portal/messages",
    notifications_url: str = "/app/notifications",
    force_login: bool = True,
):
    """Standard portal context + optional auth guard."""
    if force_login and frappe.session.user == "Guest":
        current_path = getattr(getattr(frappe, "request", None), "path", None) or "/"
        _redirect_to_login(current_path)
        return context

    user = frappe.session.user
    context.user_roles = frappe.get_roles(user)
    context.user_full_name = get_fullname(user) or frappe.db.get_value("User", user, "full_name") or user
    context.user_avatar_url = _best_user_image_url(user)
    context.page_h1 = page_h1
    context.portal_messages_url = messages_url
    context.portal_notifications_url = notifications_url
    return context
