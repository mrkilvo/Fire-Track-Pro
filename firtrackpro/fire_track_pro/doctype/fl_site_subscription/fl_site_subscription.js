frappe.ui.form.on("FL Site Subscription", {
	refresh(frm) {
		if (!frm.is_new()) {
			const base = Number(frm.doc.base_users_included || 0);
			const extra = Number(frm.doc.extra_users_purchased || 0);
			const total = Math.max(0, base + extra);
			if (Number(frm.doc.allowed_users_total || 0) !== total) {
				frm.set_value("allowed_users_total", total);
			}
		}
	},
	base_users_included(frm) {
		const base = Number(frm.doc.base_users_included || 0);
		const extra = Number(frm.doc.extra_users_purchased || 0);
		frm.set_value("allowed_users_total", Math.max(0, base + extra));
	},
	extra_users_purchased(frm) {
		const base = Number(frm.doc.base_users_included || 0);
		const extra = Number(frm.doc.extra_users_purchased || 0);
		frm.set_value("allowed_users_total", Math.max(0, base + extra));
	},
});
