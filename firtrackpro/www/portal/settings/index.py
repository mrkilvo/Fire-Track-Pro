import frappe

from firtrackpro.utils.demo import get_settings_context


def get_context(context):
    s = get_settings_context()
    company = {
        "company_name": s.system_name,
        "abn": "12 345 678 901",
        "phone": "+61 3 9999 9999",
        "email": s.support_email,
        "address": "Level 10, 123 Collins St, Melbourne VIC 3000",
        "logo": s.logo,
        "favicon": s.favicon,
        "currency": s.currency,
        "footer_note": s.footer_note,
        "lat": "-37.8136",
        "lon": "144.9631",
    }
    firelink = {
        "enabled": s.show_firelink,
        "share_mode": "opt_in",
        "allow_site_history_sharing": 1,
        "allow_asset_register_sharing": 1,
        "allow_defect_sharing": 1,
        "lock_on_publish": 1,
        "webhook_url": "https://firelink.example.com/webhook",
        "api_key": "FLK_demo_123",
        "org_slug": "demo-org",
    }
    apis = {
        "stripe_enabled": 1,
        "stripe_public_key": "pk_test_123",
        "stripe_secret_key": "sk_test_123",
        "stripe_webhook_secret": "whsec_123",
        "auspost_enabled": 0,
        "auspost_api_key": "",
        "openstreetmap_enabled": 1,
        "google_maps_enabled": 0,
        "google_maps_key": "",
    }
    colors = {
        "primary_color": s.primary_color,
        "accent_color": s.accent_color,
        "sidebar_bg": "#0F172A",
        "sidebar_text": "#FFFFFF",
        "danger_color": "#DC2626",
        "warning_color": "#F59E0B",
        "success_color": "#16A34A",
        "info_color": "#0369A1",
    }
    context.SETTINGS = s
    context.COMPANY = frappe._dict(company)
    context.FIRELINK = frappe._dict(firelink)
    context.APIS = frappe._dict(apis)
    context.COLORS = frappe._dict(colors)
    return context
