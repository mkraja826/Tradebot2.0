"""Fixture-only WSGI transport. Requires trusted TLS termination and access control.
Do not expose publicly. No production queue or executor integration."""
import json
import base64
import re

def application(api, origin, rp_id, credential_ids):
    def app(env, start):
        def reply(status, value):
            body=json.dumps(value).encode()
            start(status,[("Content-Type","application/json"),("Cache-Control","no-store"),("X-Content-Type-Options","nosniff"),("Content-Length",str(len(body)))])
            return [body]
        if env.get("wsgi.url_scheme")!="https" or env.get("HTTP_ORIGIN")!=origin:
            return reply("403 Forbidden",{"error":"forbidden"})
        if env.get("REQUEST_METHOD")!="POST" or env.get("CONTENT_TYPE")!="application/json":
            return reply("405 Method Not Allowed",{"error":"invalid method or content type"})
        match=re.fullmatch(r"/fixture/([0-9a-f]{32})/(request|challenge|approve)",env.get("PATH_INFO",""))
        if not match:
            return reply("404 Not Found",{"error":"not found"})
        try:
            size=int(env.get("CONTENT_LENGTH","0"))
            if not 0<size<=65536:
                raise ValueError("invalid size")
            data=json.loads(env["wsgi.input"].read(size))
            if not isinstance(data,dict):
                raise ValueError("invalid body")
            request_id,action=match.groups()
            if action=="request" and not data:
                return reply("200 OK",api.request(request_id))
            if action=="challenge" and not data:
                result=api.challenge(request_id)
                encode=lambda b:base64.urlsafe_b64encode(b).decode().rstrip("=")
                result["challenge"]=encode(bytes.fromhex(result["challenge"]))
                result["rpId"]=rp_id
                result["allowCredentials"]=[{"id":encode(c)} for c in credential_ids]
                return reply("200 OK",result)
            if action=="approve" and set(data)=={"nonce","assertion"}:
                api.approve(request_id,data["nonce"],data["assertion"])
                # Never expose signed approval envelopes to the browser.
                return reply("200 OK",{"status":"fixture_verified","execution_effect":"none"})
            raise ValueError("invalid request")
        except (ValueError,TypeError,KeyError):
            return reply("400 Bad Request",{"error":"request rejected"})
    return app
