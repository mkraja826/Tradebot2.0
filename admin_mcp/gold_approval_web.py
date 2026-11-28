"""Gold approval WSGI routes for a trusted HTTPS mount on the dashboard."""
import base64
import json
import re
import sqlite3
from pathlib import Path

from approval_verify import request_digest
from operator_auth import approval_challenge

HOST = "tradingbot.micirql.com"
ORIGIN = "https://" + HOST
BASE = "/admin/approvals"
ASSETS = {
    BASE: ("gold_approval.html", "text/html; charset=utf-8"),
    BASE + "/page.js": ("gold_approval.js", "text/javascript"),
    BASE + "/approval_browser.js": ("approval_browser.js", "text/javascript"),
}


def application(api, credential_ids):
    if api.policy.get("origin") != ORIGIN or api.policy.get("rp_id") != HOST:
        raise ValueError("approval host policy mismatch")

    def app(env, start):
        def send(status, payload, mime="application/json"):
            if mime == "application/json":
                payload = json.dumps(payload).encode()
            start(status, [("Content-Type", mime), ("Cache-Control", "no-store"),
                           ("Referrer-Policy", "no-referrer"), ("X-Content-Type-Options", "nosniff"),
                           ("Content-Security-Policy", "default-src 'none'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")])
            return [payload]

        if env.get("wsgi.url_scheme") != "https" or env.get("HTTP_HOST") not in (HOST, HOST + ":443"):
            return send("403 Forbidden", {})
        path = env.get("PATH_INFO", "")
        if env.get("REQUEST_METHOD") == "GET" and path in ASSETS:
            name, mime = ASSETS[path]
            return send("200 OK", Path(__file__).with_name(name).read_bytes(), mime)
        match = re.fullmatch(BASE + r"/([0-9a-f]{32})/(review|challenge|approve)", path)
        if not match:
            return send("404 Not Found", {})
        if env.get("REQUEST_METHOD") != "POST" or env.get("HTTP_ORIGIN") != ORIGIN:
            return send("403 Forbidden", {})
        try:
            size = int(env.get("CONTENT_LENGTH") or 0)
            if env.get("CONTENT_TYPE") != "application/json" or not 0 < size <= 65536:
                raise ValueError()
            body = json.loads(env["wsgi.input"].read(size))
            rid, action = match.groups()
            if type(body) is not dict:
                raise ValueError()
            record = api.request(rid)
            digest = request_digest(record)
            if action == "review" and not body:
                return send("200 OK", {"record": record, "digest": digest})
            if body.get("digest") != digest:
                return send("409 Conflict", {})
            if action == "challenge" and set(body) == {"digest"}:
                options = api.challenge(rid)
                raw = bytes.fromhex(options["challenge"])
                if raw != approval_challenge(record, options["nonce"]):
                    return send("409 Conflict", {})
                def encode(data):
                    return base64.urlsafe_b64encode(data).decode().rstrip("=")
                return send("200 OK", {"nonce": options["nonce"], "challenge": encode(raw),
                                       "rpId": HOST, "allowCredentials": [
                                           {"id": encode(cid)} for cid in credential_ids]})
            if action == "approve" and set(body) == {"nonce", "assertion", "digest"}:
                if not isinstance(body["assertion"], str) or len(body["assertion"]) > 32768:
                    raise ValueError()
                receipt = api.approve(rid, body["nonce"], body["assertion"])
                return send("200 OK", {"request_id": rid, "status": receipt["status"]})
        except (ValueError, KeyError, TypeError, sqlite3.IntegrityError):
            return send("400 Bad Request", {})
        return send("400 Bad Request", {})
    return app
