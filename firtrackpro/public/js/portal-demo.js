// Fire Track Pro - portal demo helpers (modals, chips, slideovers)
window.FTP = window.FTP || {};

FTP.modal = (function () {
	function open(id) {
		const m = document.getElementById(id);
		if (!m) return;
		m.classList.remove("hidden");
		document.body.classList.add("overflow-hidden");
	}
	function close(id) {
		const m = document.getElementById(id);
		if (!m) return;
		m.classList.add("hidden");
		document.body.classList.remove("overflow-hidden");
	}
	function bind() {
		document.addEventListener("click", (e) => {
			const openBtn = e.target.closest("[data-modal-open]");
			if (openBtn) {
				e.preventDefault();
				open(openBtn.getAttribute("data-modal-open"));
				return;
			}
			const closeBtn = e.target.closest("[data-modal-close]");
			if (closeBtn) {
				e.preventDefault();
				close(closeBtn.getAttribute("data-modal-close"));
				return;
			}
			const overlay = e.target.closest(".ftp-modal");
			if (overlay && e.target === overlay) {
				close(overlay.id);
			}
		});
	}
	return { open, close, bind };
})();

FTP.drawer = (function () {
	function open(id) {
		const d = document.getElementById(id);
		if (!d) return;
		d.classList.remove("translate-x-full");
		d.setAttribute("aria-hidden", "false");
		document.body.classList.add("overflow-hidden");
	}
	function close(id) {
		const d = document.getElementById(id);
		if (!d) return;
		d.classList.add("translate-x-full");
		d.setAttribute("aria-hidden", "true");
		document.body.classList.remove("overflow-hidden");
	}
	function bind() {
		document.addEventListener("click", (e) => {
			const openBtn = e.target.closest("[data-drawer-open]");
			if (openBtn) {
				e.preventDefault();
				open(openBtn.getAttribute("data-drawer-open"));
				return;
			}
			const closeBtn = e.target.closest("[data-drawer-close]");
			if (closeBtn) {
				e.preventDefault();
				close(closeBtn.getAttribute("data-drawer-close"));
				return;
			}
		});
	}
	return { open, close, bind };
})();

FTP.badge = function (status) {
	const m = {
		Paid: "badge--ok",
		Completed: "badge--ok",
		Accepted: "badge--ok",
		Active: "badge--ok",
		Compliant: "badge--ok",
		Overdue: "badge--warn",
		Due: "badge--warn",
		Open: "badge--warn",
		"In Progress": "badge--warn",
		Draft: "badge--warn",
		Scheduled: "badge--warn",
		Failed: "badge--err",
		Declined: "badge--err",
		Error: "badge--err",
		Cancelled: "badge--err",
	};
	const cls = m[status] || "badge--warn";
	return `<span class="${cls}">${status}</span>`;
};

document.addEventListener("DOMContentLoaded", () => {
	FTP.modal.bind();
	FTP.drawer.bind();
});
