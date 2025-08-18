import os
import re

import frappe

EXTENDS_RE = re.compile(r'{%\s*extends\s+"([^"]+)"\s*%}')
BLOCK_RE = re.compile(r"{%\s*block\s+([a-zA-Z0-9_]+)\s*%}")
END_BLOCK_RE = re.compile(r"{%\s*endblock\s*%}")


def scan_html(full_path):
	issues = []
	try:
		with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
			s = f.read()
	except Exception:
		return ["unreadable"]
	m = EXTENDS_RE.search(s)
	if not m:
		issues.append("missing_extends")
	else:
		tpl = m.group(1)
		if "portal_template.html" not in tpl and "/portal/" in full_path.replace("\\", "/"):
			issues.append("extends_not_portal_template")
	blocks = BLOCK_RE.findall(s)
	if blocks.count("page_content") > 1:
		issues.append("page_content_defined_twice")
	if s.count("{% block") != s.count("{% endblock"):
		issues.append("unbalanced_blocks")
	return issues


def walk_www():
	base = frappe.get_app_path("firtrackpro", "www")
	pages = []
	for root, _, files in os.walk(base):
		for fn in files:
			if not fn.endswith((".html", ".py")):
				continue
			full = os.path.join(root, fn)
			rel = os.path.relpath(full, base).replace(os.sep, "/")
			if "/templates/" in rel:
				continue
			url = "/" + rel
			if url.endswith("/index.html") or url.endswith("/index.py"):
				url = url.rsplit("/index.", 1)[0] or "/"
			else:
				url = url.rsplit(".", 1)[0]
				if not url.startswith("/"):
					url = "/" + url
			issues = scan_html(full) if fn.endswith(".html") else []
			pages.append(
				{
					"url": url,
					"path": rel,
					"is_index": fn.startswith("index."),
					"issues": issues,
					"type": "html" if fn.endswith(".html") else "py",
				}
			)
	pages.sort(key=lambda x: (x["url"], x["type"]))
	return pages


def missing_indexes(pages):
	dirs = {}
	for p in pages:
		d = p["path"].rsplit("/", 1)[0] if "/" in p["path"] else ""
		dirs.setdefault(d, []).append(p)
	out = []
	for d, items in dirs.items():
		if d and not any(i["is_index"] for i in items):
			out.append(d)
	return sorted(set(out))


def get_context(context):
	pages = walk_www()
	context.pages = pages
	context.missing_indexes = missing_indexes(pages)
	return context
