import os, frappe

def file_routes():
    base = frappe.get_app_path('firtrackpro', 'www')
    out = {}
    for root, _, files in os.walk(base):
        for fn in files:
            if not fn.endswith(('.html', '.py')):
                continue
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, base).replace(os.sep, '/')
            if '/templates/' in rel:
                continue
            url = '/' + rel
            if url.endswith('/index.html') or url.endswith('/index.py'):
                url = url.rsplit('/index.', 1)[0] or '/'
            else:
                url = url.rsplit('.', 1)[0]
                if not url.startswith('/'):
                    url = '/' + url
            rec = out.get(url) or {'url': url, 'paths': [], 'types': set()}
            rec['paths'].append(rel)
            rec['types'].add('html' if fn.endswith('.html') else 'py')
            out[url] = rec
    for rec in out.values():
        rec['types'] = sorted(rec['types'])
    return sorted(out.values(), key=lambda r: r['url'])

def web_pages():
    try:
        rows = frappe.get_all('Web Page', filters={'published': 1}, fields=['route','title'], limit_page_length=1000)
    except Exception:
        rows = []
    out = []
    for r in rows:
        url = '/' + r.route.strip('/')
        out.append({'url': url, 'paths': [f'Web Page: {r.title or r.route}'], 'types': ['web_page']})
    return sorted(out, key=lambda r: r['url'])

def dedupe(a, b):
    idx = {i['url']: {**i, 'types': set(i.get('types', [])), 'paths': list(i.get('paths', []))} for i in a}
    for j in b:
        if j['url'] in idx:
            idx[j['url']]['paths'] += j.get('paths', [])
            idx[j['url']]['types'] |= set(j.get('types', []))
        else:
            idx[j['url']] = {**j, 'types': set(j.get('types', [])), 'paths': list(j.get('paths', []))}
    out = []
    for v in idx.values():
        v['types'] = sorted(v['types'])
        out.append(v)
    out.sort(key=lambda r: r['url'])
    return out

def get_context(context):
    files = file_routes()
    pages = dedupe(files, web_pages())
    context.pages = pages
    context.file_count = len(files)
    context.webpage_count = sum(1 for p in pages if 'web_page' in p['types'])
    return context
