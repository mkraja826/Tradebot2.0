"""Enrollment gateway. Mount only behind a trusted HTTPS proxy.
The proxy must sanitize forwarding headers and redact authorization headers.
"""
import base64
import json
import re
import sqlite3
from pathlib import Path
from contextlib import closing
from enrollment_session_binding import options
from enrollment_atomic import complete

HOST = "tradingbot.micirql.com"
ORIGIN = "https://" + HOST
BASE = "/admin/enroll"
ASSETS = {
    BASE: ("enrollment.html", "text/html; charset=utf-8"),
    BASE + "/page.js": ("enrollment_page.js", "text/javascript"),
    BASE + "/enrollment_browser.js": ("enrollment_browser.js", "text/javascript"),
}

def application(connect, policy):
    if policy.get("origin") != ORIGIN or policy.get("rp_id") != HOST:
        raise ValueError("invalid host policy")
    def app(env, start):
        def send(status, payload, mime="application/json"):
            if mime == "application/json":
                payload = json.dumps(payload).encode()
            start(status, [("Content-Type", mime), ("Cache-Control", "no-store"),
                ("Referrer-Policy", "no-referrer"), ("X-Content-Type-Options", "nosniff"),
                ("Content-Security-Policy", "default-src 'none'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")])
            return [payload]
        if env.get("wsgi.url_scheme") != "https" or env.get("HTTP_HOST") not in (HOST, HOST+":443"):
            return send("403 Forbidden", {})
        path = env.get("PATH_INFO", "")
        method = env.get("REQUEST_METHOD")
        if method == "GET" and path in ASSETS:
            name, mime = ASSETS[path]
            return send("200 OK", Path(__file__).with_name(name).read_bytes(), mime)
        if path not in (BASE+"/options", BASE+"/complete"):
            return send("404 Not Found", {})
        if method != "POST" or env.get("HTTP_ORIGIN") != ORIGIN:
            return send("403 Forbidden", {})
        match = re.fullmatch(r"Bearer ([0-9a-f]{64})", env.get("HTTP_AUTHORIZATION", ""))
        if not match:
            return send("403 Forbidden", {})
        token = match.group(1)
        try:
            size = int(env.get("CONTENT_LENGTH") or 0)
            if env.get("CONTENT_TYPE") != "application/json" or not 0 < size <= 131072:
                raise ValueError()
            body = json.loads(env["wsgi.input"].read(size))
            if type(body) is not dict:
                raise ValueError()
            operator = body.get("operator")
            if not isinstance(operator, str) or not 0 < len(operator) <= 128:
                raise ValueError()
            with closing(connect()) as db:
                if path == BASE+"/options" and set(body) == {"operator"}:
                    return send("200 OK", options(db, policy, token, operator))
                if path == BASE+"/complete" and set(body) == {"operator","challenge","response"}:
                    encoded = body["challenge"]
                    if not isinstance(encoded,str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}",encoded):
                        raise ValueError()
                    challenge = base64.urlsafe_b64decode(encoded+"=")
                    complete(db, policy, token, operator, challenge, body["response"])
                    return send("200 OK", {"status":"registered"})
                raise ValueError()
        except PermissionError:
            return send("403 Forbidden", {})
        except (ValueError, TypeError, KeyError, sqlite3.IntegrityError):
            return send("400 Bad Request", {})
        except Exception:
            return send("503 Service Unavailable", {})
    return app
