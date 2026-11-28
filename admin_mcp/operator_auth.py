"""Policy boundary for a future independently hosted WebAuthn verifier.
Not an HTTP endpoint. Never accept caller-supplied verification results from MCP.
"""
import hashlib
import hmac
import re
from approval_verify import canonical, request_digest

def approval_challenge(request, nonce):
    if not isinstance(nonce, str) or not re.fullmatch("[0-9a-f]{64}", nonce):
        raise ValueError("invalid challenge nonce")
    return hashlib.sha256(canonical({"purpose":"tb2-admin-approval-v1","digest":request_digest(request),"nonce":nonce})).digest()

def issue_after_verification(request, nonce, assertion, verify_assertion, policy, key, now):
    """Trusted gateway only: verify_assertion must be a real WebAuthn verifier.
    It must validate signature, challenge, RP ID, origin, user verification,
    credential ownership and atomic challenge consumption. No default verifier.
    """
    if not isinstance(key, bytes) or len(key)<32 or type(now) is not int:
        raise ValueError("invalid gateway configuration")
    challenge=approval_challenge(request,nonce)
    operator=verify_assertion(assertion,challenge,policy)
    if not isinstance(operator,str) or operator not in policy["operators"]:
        raise ValueError("operator not authorized")
    claims={"digest":request_digest(request),"audience":policy["audience"],
            "operator":operator,"issued":now,"expires":now+120,"nonce":nonce[:32]}
    return {"claims":claims,"signature":hmac.new(key,canonical(claims),hashlib.sha256).hexdigest()}
