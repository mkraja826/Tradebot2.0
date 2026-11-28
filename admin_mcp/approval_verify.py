"""Offline verification prototype. Not wired to MCP or an executor."""
import hashlib
import hmac
import json
import re

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")

def request_digest(request):
    return hashlib.sha256(canonical(request)).hexdigest()

def verify(request, envelope, key, now, audience, allowed_operators):
    """Verify an independently issued HMAC envelope; executor must consume nonce atomically."""
    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError("invalid verifier configuration")
    if not isinstance(envelope, dict) or set(envelope) != {"claims", "signature"}:
        raise ValueError("invalid envelope")
    claims = envelope["claims"]
    fields = {"digest", "audience", "operator", "issued", "expires", "nonce"}
    if not isinstance(claims, dict) or set(claims) != fields:
        raise ValueError("invalid claims")
    sig = envelope["signature"]
    if not isinstance(sig, str) or not re.fullmatch("[0-9a-f]{64}", sig):
        raise ValueError("invalid signature")
    expected = hmac.new(key, canonical(claims), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise ValueError("invalid signature")
    if claims["audience"] != audience or claims["operator"] not in allowed_operators:
        raise ValueError("unauthorized approval")
    issued, expires = claims["issued"], claims["expires"]
    if type(issued) is not int or type(expires) is not int or not issued <= now < expires or not 0 < expires-issued <= 300:
        raise ValueError("invalid approval lifetime")
    if not isinstance(claims["nonce"], str) or not re.fullmatch("[0-9a-f]{32}", claims["nonce"]):
        raise ValueError("invalid nonce")
    if claims["digest"] != request_digest(request):
        raise ValueError("request mismatch")
    return dict(claims)
