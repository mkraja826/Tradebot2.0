"""Loopback-only HTTP presentation of isolated research status."""
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
import json
from urllib.parse import urlsplit,parse_qs
from tradebot.dashboard_chart_v3 import chart,profiles
from tradebot.dashboard_account_history_v3 import account_view
from tradebot.dashboard_snapshot_v3 import snapshot

def handler(root):
    page=Path(__file__).with_name("dashboard_v3.html").read_bytes()
    script=Path(__file__).with_name("dashboard_v3.js").read_bytes()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get("Host") != "127.0.0.1:"+str(self.server.server_port):
                self.send(403,"text/plain",b"Local host required"); return
            if self.path=="/":
                self.send(200,"text/html; charset=utf-8",page)
            elif self.path=="/assets/dashboard-v3.js?v=20261124-3":
                self.send(200,"application/javascript; charset=utf-8",script)
            elif self.path=="/api/status":
                try: body=json.dumps(snapshot(root),allow_nan=False).encode()
                except Exception: self.send(503,"application/json",b'{"status":"unavailable"}'); return
                self.send(200,"application/json",body)
            elif urlsplit(self.path).path in ("/api/chart","/api/strategies","/api/account-history"):
                try:
                    u=urlsplit(self.path);q=parse_qs(u.query,strict_parsing=True,max_num_fields=2)
                    expected={"symbol","frame"} if u.path=="/api/chart" else {"symbol"}
                    if set(q)!=expected or any(len(v)!=1 for v in q.values()):raise ValueError()
                    result=chart(root,q["symbol"][0],q["frame"][0]) if u.path=="/api/chart" else profiles(root,q["symbol"][0]) if u.path=="/api/strategies" else account_view(root,q["symbol"][0])
                    body=json.dumps(result,allow_nan=False).encode()
                except ValueError:self.send(400,"application/json",b'{"status":"invalid_or_unavailable"}');return
                except Exception:self.send(503,"application/json",b'{"status":"unavailable"}');return
                self.send(200,"application/json",body)
            else: self.send(404,"text/plain",b"Not found")
        def send(self,status,kind,body):
            self.send_response(status)
            self.send_header("Content-Type",kind)
            self.send_header("Content-Length",str(len(body)))
            self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff")
            self.send_header("X-Frame-Options","DENY")
            self.send_header("Content-Security-Policy","default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers(); self.wfile.write(body)
        def log_message(self,*args): pass
    return Handler

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(); p.add_argument("--directory",required=True,type=Path); p.add_argument("--port",type=int,default=8766)
    args=p.parse_args()
    server=HTTPServer(("127.0.0.1",args.port),handler(args.directory))
    server.serve_forever()
