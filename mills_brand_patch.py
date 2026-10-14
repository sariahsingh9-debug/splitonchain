"""Rebrand accounting presentation while leaving customer financial records untouched."""
from pathlib import Path
root = Path(__file__).resolve().parent
old = '<strong>atlas<span class="brand-dot">.</span></strong><small>LEDGER & OPERATIONS</small>'
new = '<strong class="mills-brand-name">Mills<span>Multiservices</span></strong><small>ACCOUNTING &amp; OPERATIONS</small>'

def replace(path, pairs):
    f = root / path
    s = f.read_text(encoding='utf-8')
    for a, b in pairs:
        if a not in s and b not in s:
            raise RuntimeError(f'Expected branding marker missing: {path}: {a[:65]}')
        s = s.replace(a, b)
    f.write_text(s, encoding='utf-8')

replace('templates/base.html', [(old, new), (' · Atlas Ledger</title>', ' · Mills Multiservices</title>'), ('ATLAS LEDGER <span class="footer-version">', 'MILLS MULTISERVICES <span class="footer-version">'), ('/static/app.css?v=1.0','/static/app.css?v=1.1')])
replace('templates/auth.html', [(old, new), ('ATLAS LEDGER / PRIVATE BUSINESS SOFTWARE', 'MILLS MULTISERVICES / PRIVATE BUSINESS SOFTWARE'), ('Sign in to Atlas', 'Sign in to Mills Multiservices')])
replace('app.py', [("FastAPI(title='Atlas Ledger'", "FastAPI(title='Mills Multiservices'"), ('filename="atlas-{kind}.csv"', 'filename="mills-multiservices-{kind}.csv"')])
css = root / 'static/app.css'
s = css.read_text(encoding='utf-8')
marker = '/* Mills Multiservices identity v1 */'
if marker not in s:
    s += '''
/* Mills Multiservices identity v1 */
.brand strong.mills-brand-name {
    font-family:var(--head); color:white; font-size:24px; font-weight:800;
    letter-spacing:-.65px; display:block; line-height:1.02; white-space:nowrap;
}
.brand strong.mills-brand-name span {
    display:block; color:#f6fbfe; font-size:15.6px; letter-spacing:-.22px; line-height:1.3;
}
.brand:has(.mills-brand-name) small {
    font-size:7.5px;letter-spacing:.6px;white-space:nowrap;margin-top:5px;
}
@media (max-width:700px) {
    .auth-brand-panel .brand strong.mills-brand-name{font-size:21px}
    .auth-brand-panel .brand strong.mills-brand-name span{font-size:14px}
    .auth-brand-panel .brand {height:auto;min-height:46px}
}
'''
    css.write_text(s, encoding='utf-8')
print('Mills Multiservices branding applied')
