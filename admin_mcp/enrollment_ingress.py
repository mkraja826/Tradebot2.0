"""Verify Access identity before trusting external HTTPS context.
Requires PyJWT with cryptography and a trusted, locally provisioned JWKS.
"""
import json
import jwt

def protect(app, issuer, audience, jwks, allowed_subjects):
    if not issuer.startswith("https://") or not issuer.endswith(".cloudflareaccess.com") or not audience or not allowed_subjects:
        raise ValueError("incomplete Access policy")
    keys = jwt.PyJWKSet.from_dict(jwks)
    subjects = frozenset(allowed_subjects)
    def wrapped(env, start):
        try:
            if env.get("REMOTE_ADDR") != "127.0.0.1":
                raise ValueError("invalid peer")
            token = env.get("HTTP_CF_ACCESS_JWT_ASSERTION", "")
            if not token or len(token)>16384:
                raise ValueError("missing assertion")
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256":
                raise ValueError("invalid algorithm")
            matches = [key for key in keys.keys if key.key_id == header.get("kid") and key.algorithm_name == "RS256"]
            if len(matches)!=1:
                raise ValueError("unknown signing key")
            claims = jwt.decode(token,matches[0].key,algorithms=["RS256"],audience=audience,issuer=issuer,options={"require":["exp","iat","iss","aud","sub"]})
            if claims["sub"] not in subjects:
                raise ValueError("unauthorized identity")
        except Exception:
            start("403 Forbidden",[("Content-Type","application/json"),("Cache-Control","no-store")])
            return [b'{}']
        trusted = dict(env)
        trusted["wsgi.url_scheme"]="https"
        return app(trusted,start)
    return wrapped
