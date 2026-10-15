"""Presentation-only Mills logo rollout. Safe to run during each container build."""
from pathlib import Path

root=Path(__file__).resolve().parent


def update(rel, replacements):
    file=root/rel
    src=file.read_text(encoding='utf-8')
    out=src
    for old,new in replacements:
        if old not in out:
            if new in out:continue
            raise RuntimeError(f'Mills logo markup not found in {rel}: {old[:95]!r}')
        out=out.replace(old,new)
    if out != src: file.write_text(out,encoding='utf-8')

logo_icon='<span class="brand-mark"><span></span><span></span><span></span></span>'
new_icon='<span class="mills-brand-symbol-wrap"><img class="mills-brand-symbol" src="/static/mills-emblem.png?v=7" alt="Mills Multiservices logo"></span>'
update('templates/base.html', [
    (logo_icon,new_icon),
    ('</head>', '<link rel="icon" type="image/png" href="/static/mills-emblem.png?v=7"><link rel="apple-touch-icon" href="/static/mills-emblem.png?v=7"></head>'),
])
old_auth='<div class="brand">'+logo_icon+'<div><strong class="mills-brand-name">Mills<span>Multiservices</span></strong><small>ACCOUNTING &amp; OPERATIONS</small></div></div>'
new_auth='<div class="brand mills-auth-brand-wrap"><img class="mills-auth-logo" src="/static/mills-logo.png?v=7" alt="Mills Multiservices official logo"></div>'
update('templates/auth.html',[(old_auth,new_auth)])
update('templates/invoice_design.html', [
    ('<div class="paper-brand"><b>{{ setting.company_name }}</b><small>{{ design.heading }}</small></div>',
    '<div class="paper-brand"><img class="mills-document-logo" src="/static/mills-logo.png?v=7" alt="Mills Multiservices official logo"><small>{{ design.heading }}</small></div>')
])

css=root/'static/app.css'
s=css.read_text(encoding='utf-8')
marker='/* MILLS OFFICIAL LOGO v7 */'
if marker not in s:
    s+='''
/* MILLS OFFICIAL LOGO v7 */
.sidebar .brand {height:116px;padding:12px 15px 10px;gap:10px;align-items:center}
.mills-brand-symbol-wrap {width:64px;height:64px;flex:0 0 64px;border-radius:14px;background:#e7f2f9;border:1px solid #d0e0ed;display:flex;align-items:center;justify-content:center;overflow:hidden}
.mills-brand-symbol {width:61px;height:61px;object-fit:contain;display:block}
.sidebar .brand .mills-brand-name {font-size:20px;letter-spacing:-.5px;line-height:1.02}
.sidebar .brand .mills-brand-name span {font-size:14px;line-height:1.22}
.sidebar .brand small {letter-spacing:.75px;font-size:7.5px;margin-top:5px}
.auth-brand-panel .brand.mills-auth-brand-wrap {height:auto!important;min-height:0!important;width:218px;max-width:100%;padding:12px;background:#e7f2f9;border-radius:22px;border:1px solid #cbdfe9;display:flex;align-items:center;justify-content:center}
.auth-brand-panel .mills-auth-logo {display:block;width:190px;max-width:100%;height:190px;object-fit:contain}
.mills-document-logo {width:92px;max-height:92px;object-fit:contain;flex-shrink:0}
@media(max-width:760px){.sidebar .brand{height:113px;padding:10px 13px;gap:8px}.mills-brand-symbol-wrap{height:58px;width:58px;flex-basis:58px}.mills-brand-symbol{height:55px;width:55px}.sidebar .brand .mills-brand-name{font-size:19px}.auth-brand-panel .brand.mills-auth-brand-wrap{width:170px;padding:9px}.auth-brand-panel .mills-auth-logo{height:151px;width:151px}.mills-document-logo{width:72px;max-height:72px}}
'''
    css.write_text(s,encoding='utf-8')

# Use the same transparent official logo for PDF invoice headers.
pdf=root/'invoice_tools.py'
s=pdf.read_text(encoding='utf-8')
if 'MILLS_OFFICIAL_PDF_LOGO' not in s:
    imp='from pathlib import Path\n'
    if imp not in s:s=s.replace('import io, json, re\n','import io, json, re\n'+imp,1)
    s=s.replace('from reportlab.platypus import SimpleDocTemplate,','from reportlab.platypus import Image as RLImage, SimpleDocTemplate,',1)
    anchor='    items=[]\n    name=invoice.issuer_name or company.company_name'
    if anchor not in s:raise RuntimeError('Invoice PDF building position changed; refusing unsafe patch')
    insertion='''    items=[]
    # MILLS_OFFICIAL_PDF_LOGO: a transparent logo adds branding without changing invoices or accounting data.
    logo_file=Path(__file__).resolve().parent/'static'/'mills-logo.png'
    if logo_file.is_file():
        items.append(RLImage(str(logo_file), width=70, height=70))
        items.append(Spacer(1, 5))
    name=invoice.issuer_name or company.company_name'''
    s=s.replace(anchor,insertion,1)
    pdf.write_text(s,encoding='utf-8')
print('Official Mills logo installed in sidebar, sign-in, invoice preview, PDF headers, and favicon.')