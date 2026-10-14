"""Secure launcher: keep financial application offline until Postgres is connected."""
import os
from http.server import HTTPServer, BaseHTTPRequestHandler

url=os.environ.get("DATABASE_URL","")
ready=(url.startswith(("postgresql://","postgresql+psycopg://","postgres://"))
       and len(os.environ.get("SESSION_SECRET",""))>=48
       and len(os.environ.get("SETUP_TOKEN",""))>=32
       and os.environ.get("COOKIE_SECURE")=="1")

if ready:
    os.execvp("uvicorn",["uvicorn","app:app","--host","0.0.0.0","--port",os.environ.get("PORT","10000"),"--proxy-headers"])

class Waiting(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0]=="/health":
            status=503
            content=b'{"status":"configuration_pending"}'
            mime="application/json"
        else:
            status=200
            content=(b'<!doctype html><html lang="en"><meta charset="utf-8">'
            b'<meta name="viewport" content="width=device-width,initial-scale=1">'
            b'<title>Atlas Ledger - Setup Pending</title>'
            b'<style>body{font:16px system-ui;background:#f6f8fb;color:#183044;margin:0;'
            b'display:grid;min-height:100vh;place-items:center}main{padding:36px;'
            b'background:white;border-radius:20px;max-width:450px;margin:20px;'
            b'box-shadow:0 12px 50px #2333 00;}h1{font-size:28px}</style>'
            b'<main><strong>ATLAS LEDGER</strong><h1>Private setup in progress</h1>'
            b'<p>This installation is waiting for a securely linked database. '
            b'No business or financial records can be entered yet.</p>'
            b'<p>Please contact your software administrator.</p></main></html>')
            mime="text/html; charset=utf-8"
        self.send_response(status)
        self.send_header("Content-Type",mime)
        self.send_header("Content-Length",str(len(content)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.end_headers()
        self.wfile.write(content)
    def log_message(self,fmt,*args):
        pass

HTTPServer(("0.0.0.0",int(os.environ.get("PORT","10000"))),Waiting).serve_forever()
