import frappe

from firtrackpro.portal_utils import build_portal_context

no_cache = 1


def get_context(context):
	context.PAGE_TITLE = "Invoices"
	context.actions = ["export"]
	context.INVOICES = [
		{
			"id": "INV-2025-101",
			"customer": "Initech Pty Ltd",
			"status": "Paid",
			"total": "$1,766.00",
			"updated": "07 Aug 2025",
		},
		{
			"id": "INV-2025-102",
			"customer": "Globex Pty Ltd",
			"status": "Draft",
			"total": "$5,895.00",
			"updated": "10 Aug 2025",
		},
		{
			"id": "INV-2025-103",
			"customer": "ACME Pty Ltd",
			"status": "Overdue",
			"total": "$2,147.00",
			"updated": "11 Aug 2025",
		},
		{
			"id": "INV-2025-104",
			"customer": "ACME Pty Ltd",
			"status": "Overdue",
			"total": "$1,703.00",
			"updated": "15 Aug 2025",
		},
		{
			"id": "INV-2025-105",
			"customer": "Umbrella Ltd",
			"status": "Overdue",
			"total": "$4,372.00",
			"updated": "22 Aug 2025",
		},
		{
			"id": "INV-2025-106",
			"customer": "ACME Pty Ltd",
			"status": "Overdue",
			"total": "$6,301.00",
			"updated": "18 Aug 2025",
		},
		{
			"id": "INV-2025-107",
			"customer": "Umbrella Ltd",
			"status": "Overdue",
			"total": "$2,059.00",
			"updated": "12 Aug 2025",
		},
		{
			"id": "INV-2025-108",
			"customer": "Umbrella Ltd",
			"status": "Paid",
			"total": "$2,433.00",
			"updated": "05 Aug 2025",
		},
		{
			"id": "INV-2025-109",
			"customer": "ACME Pty Ltd",
			"status": "Paid",
			"total": "$3,038.00",
			"updated": "12 Aug 2025",
		},
		{
			"id": "INV-2025-110",
			"customer": "ACME Pty Ltd",
			"status": "Overdue",
			"total": "$4,288.00",
			"updated": "04 Aug 2025",
		},
		{
			"id": "INV-2025-111",
			"customer": "ACME Pty Ltd",
			"status": "Paid",
			"total": "$7,074.00",
			"updated": "05 Aug 2025",
		},
		{
			"id": "INV-2025-112",
			"customer": "Umbrella Ltd",
			"status": "Overdue",
			"total": "$2,743.00",
			"updated": "10 Aug 2025",
		},
		{
			"id": "INV-2025-113",
			"customer": "Globex Pty Ltd",
			"status": "Paid",
			"total": "$6,196.00",
			"updated": "20 Aug 2025",
		},
		{
			"id": "INV-2025-114",
			"customer": "Umbrella Ltd",
			"status": "Overdue",
			"total": "$3,397.00",
			"updated": "15 Aug 2025",
		},
		{
			"id": "INV-2025-115",
			"customer": "Initech Pty Ltd",
			"status": "Overdue",
			"total": "$2,476.00",
			"updated": "15 Aug 2025",
		},
		{
			"id": "INV-2025-116",
			"customer": "Initech Pty Ltd",
			"status": "Draft",
			"total": "$3,711.00",
			"updated": "19 Aug 2025",
		},
		{
			"id": "INV-2025-117",
			"customer": "ACME Pty Ltd",
			"status": "Paid",
			"total": "$956.00",
			"updated": "06 Aug 2025",
		},
	]
	return build_portal_context(context, page_h1="Invoices", force_login=True)
