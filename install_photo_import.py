"""Install isolated OCR module into the built accounting app, without touching production database rows."""
from pathlib import Path
root=Path(__file__).resolve().parent
app=root/'app.py'
s=app.read_text(encoding='utf-8')
marker='# Automatic private OCR of multiple paper invoices with mandatory human review.'
if marker not in s:
    needle="register_invoice_tools(app, {"
    if needle not in s: raise RuntimeError('Expected invoice tools installation not found')
    s += """
\n# Automatic private OCR of multiple paper invoices with mandatory human review.
from photo_import import register as register_photo_import
register_photo_import(app, {
    'render':render, 'require':require, 'check_csrf':check_csrf, 'redirect':redirect,
    'flash':flash, 'audit':audit, 'parse_date':parse_date, 'money_cents':money_cents,
    'fx_value':fx_value, 'next_number':next_number,
})
"""
    app.write_text(s,encoding='utf-8')
base=root/'templates/base.html'
s=base.read_text(encoding='utf-8')
if 'href="/paper-invoices/photos"' not in s:
    needle='href="/paper-invoices/new"'
    pos=s.find(needle)
    if pos<0: raise RuntimeError('Paper invoice menu missing')
    start=s.rfind('\n',0,pos)+1
    line_end=s.find('\n',pos)
    anchor=s[start:line_end]
    insert='   {% if user.role in [\'admin\',\'accountant\'] %}<a class="nav-item {% if nav==\'photos\' %}active{% endif %}" href="/paper-invoices/photos"><svg><use href="#i-file"/></svg>Scan invoice photos</a>{% endif %}\n'
    s=s[:line_end+1]+insert+s[line_end+1:]
if '/static/photo_import.css' not in s:
    s=s.replace('</head>','<link rel="stylesheet" href="/static/photo_import.css?v=4"><script defer src="/static/photo_import.js?v=4"></script></head>',1)
# Hide manual paper invoice entry from navigation; retain the existing route and records.
manual_link = 'Enter paper invoice</a>{% endif %}'
lines=s.splitlines(keepends=True)
old_nav=[line for line in lines if manual_link in line and 'href="/paper-invoices/new"' in line]
if len(old_nav)!=1:
    raise RuntimeError(f'Expected exactly one manual paper invoice menu item, found {len(old_nav)}')
s=s.replace(old_nav[0],'')
base.write_text(s,encoding='utf-8')
print('Mills invoice photo OCR and private review registered.')
