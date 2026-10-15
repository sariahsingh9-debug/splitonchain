"""Install decorative sidebar animation without touching financial data."""
from pathlib import Path
root = Path(__file__).resolve().parent
if not (root / "static/sidebar_ambient.css").is_file():
    raise RuntimeError("Sidebar stylesheet missing")
base = root / "templates/base.html"
html = base.read_text(encoding="utf-8")
asset = '<link rel="stylesheet" href="/static/sidebar_ambient.css?v=1">'
if asset not in html:
    if '<aside class="sidebar" id="sidebar">' not in html or "</head>" not in html:
        raise RuntimeError("Expected sidebar template missing")
    html = html.replace("</head>", asset + "</head>", 1)
    base.write_text(html, encoding="utf-8")
print("Animated red/blue sidebar stylesheet installed.")
