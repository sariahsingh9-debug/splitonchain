"""Include the animated red-blue accent CSS after the base and sidebar styles.
No database changes, financial writes, or application logic modifications.
"""
from pathlib import Path
root=Path(__file__).resolve().parent
css=root/'static/login_cash_ambient.css'
if not css.is_file() or "millsCashAmbient" not in css.read_text(encoding='utf-8'):
    raise RuntimeError("Missing login and cash animation stylesheet")
auth=(root/'templates/auth.html').read_text(encoding='utf-8')
dash=(root/'templates/dashboard.html').read_text(encoding='utf-8')
if 'auth-brand-panel' not in auth or 'cash-panel' not in dash:
    raise RuntimeError('Expected login or cash panel markup not found')
base=root/'templates/base.html'
source=base.read_text(encoding='utf-8')
tag='<link rel="stylesheet" href="/static/login_cash_ambient.css?v=1">'
if tag not in source:
    if '</head>' not in source:
        raise RuntimeError('Missing template head tag')
    source=source.replace('</head>',tag+'</head>',1)
    base.write_text(source,encoding='utf-8')
print('Mills login and cash card ambient gradient animations enabled.')
