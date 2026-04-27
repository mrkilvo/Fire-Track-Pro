import json
import sys
sys.path.insert(0, '/home/kilvo/frappe-bench-v16/apps/frappe')
sys.path.insert(0, '/home/kilvo/frappe-bench-v16/apps/erpnext')
sys.path.insert(0, '/home/kilvo/frappe-bench-v16/apps/firtrackpro')
import frappe
from firtrackpro.api.integrations import _local_create_signup_request
payload = {
  'subscription_plan': 'Growth',
  'company_legal_name': 'Test Signup Pty Ltd',
  'company_trading_name': 'Test Signup',
  'company_abn': '12345678901',
  'company_address': '1 Test Street',
  'company_size': 20,
  'domain_option': 'subdomain',
  'requested_subdomain': 'test-signup-direct',
  'contact_name': 'Pat Example',
  'contact_email': 'pat@example.com',
  'contact_phone': '0400000000',
  'accounts_email': 'accounts@example.com',
  'admin_first_name': 'Pat',
  'admin_last_name': 'Example',
  'admin_username': 'pat.example',
  'admin_password': 'TempPass123!',
  'managed_website_option': 0,
  'voip_option': 0,
  'activation_notes': 'Smoke test',
  'source_url': 'https://dev.firetrackpro.com.au/signup'
}
frappe.init(site='dev.firetrackpro.com.au', sites_path='/home/kilvo/frappe-bench-v16/sites')
frappe.connect()
row = _local_create_signup_request(payload)
print(json.dumps(row))
frappe.destroy()
