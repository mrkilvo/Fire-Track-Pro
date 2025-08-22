// Fire Track Pro portal navigation
(function () {
	function ready(fn) {
		document.readyState === "loading"
			? document.addEventListener("DOMContentLoaded", fn)
			: fn();
	}
	ready(function () {
		try {
			if (window.feather && feather.replace) feather.replace();
		} catch (e) {}

		var path = (window.location.pathname || "").replace(/\/$/, "");

		[
			{ root: document.getElementById("sidebar-desktop"), store: "ftp_nav_open_desktop" },
			{ root: document.getElementById("mobile-sidebar"), store: "ftp_nav_open_mobile" },
		].forEach(function (ctx) {
			if (!ctx.root) return;

			// Toggle submenus
			ctx.root.querySelectorAll(".nav-toggle").forEach(function (btn) {
				var id = btn.getAttribute("data-target");
				if (!id) return;
				var sub = document.getElementById(id);
				if (!sub) return;

				btn.addEventListener("click", function () {
					var closed = sub.classList.contains("hidden");
					if (closed) {
						sub.classList.remove("hidden", "opacity-0", "max-h-0");
						sub.classList.add("opacity-100", "max-h-96");
						btn.classList.add("open");
					} else {
						sub.classList.add("opacity-0", "max-h-0");
						sub.classList.remove("opacity-100", "max-h-96");
						setTimeout(function () {
							sub.classList.add("hidden");
						}, 160);
						btn.classList.remove("open");
					}
					save(ctx);
				});
			});

			// Active link & auto-open parents
			ctx.root.querySelectorAll("a.sidebar-link").forEach(function (a) {
				var href = (a.getAttribute("href") || "").replace(/\/$/, "");
				if (href && href === path) {
					a.classList.add("active", "bg-active");
					var p = a.parentElement;
					while (p && p !== ctx.root) {
						if (p.classList && p.classList.contains("nav-sub")) {
							p.classList.remove("hidden", "opacity-0", "max-h-0");
							p.classList.add("opacity-100", "max-h-96");
							var pid = p.getAttribute("id");
							var t = ctx.root.querySelector(
								'.nav-toggle[data-target="' + pid + '"]'
							);
							if (t) t.classList.add("open");
						}
						p = p.parentElement;
					}
				}
			});

			// Restore expanded groups
			try {
				var ids = JSON.parse(localStorage.getItem(ctx.store) || "[]");
				ids.forEach(function (id) {
					var sub = document.getElementById(id);
					if (!sub) return;
					sub.classList.remove("hidden", "opacity-0", "max-h-0");
					sub.classList.add("opacity-100", "max-h-96");
					var t = ctx.root.querySelector('.nav-toggle[data-target="' + id + '"]');
					if (t) t.classList.add("open");
				});
			} catch (e) {}

			function save(ctx) {
				var open = Array.prototype.slice
					.call(ctx.root.querySelectorAll(".nav-sub"))
					.filter(function (el) {
						return !el.classList.contains("hidden");
					})
					.map(function (el) {
						return el.id;
					});
				localStorage.setItem(ctx.store, JSON.stringify(open));
			}
		});

		// Mobile drawer events
		var openBtn = document.getElementById("mobile-menu-btn");
		var closeBtn = document.getElementById("mobile-menu-close");
		var sidebar = document.getElementById("mobile-sidebar");
		var overlay = document.getElementById("mobile-sidebar-overlay");

		function openSidebar() {
			if (sidebar && overlay) {
				sidebar.classList.remove("-translate-x-full");
				overlay.classList.remove("hidden");
			}
		}
		function closeSidebar() {
			if (sidebar && overlay) {
				sidebar.classList.add("-translate-x-full");
				overlay.classList.add("hidden");
			}
		}

		if (openBtn) openBtn.addEventListener("click", openSidebar);
		if (closeBtn) closeBtn.addEventListener("click", closeSidebar);
		if (overlay) overlay.addEventListener("click", closeSidebar);

		// Title
		var tt = document.getElementById("topbar-title");
		if (tt) {
			var active = document.querySelector('a.sidebar-link[href="' + path + '"] span');
			tt.textContent = active ? active.textContent.trim() : document.title || "Dashboard";
		}
	});
})();
