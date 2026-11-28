"""Offline enrollment controller. Only an independently authenticated
local provisioning administrator may invoke these functions.
Do not expose through MCP or public HTTP.
"""
import secrets
import time
from enrollment_store import add_enrollment_challenge, register_verified
from passkey_enroll import verify_enrollment

HOST = "tradingbot.micirql.com"

def check_scope(operator, policy):
    if policy.get("rp_id") != HOST or policy.get("origin") != "https://" + HOST:
        raise ValueError("invalid enrollment origin")
    if not isinstance(operator, str) or not operator or operator not in policy["operators"]:
        raise ValueError("unauthorized operator")

def begin(db, operator, policy):
    check_scope(operator, policy)
    challenge = secrets.token_bytes(32)
    add_enrollment_challenge(db, challenge, operator, int(time.time()) + 300)
    return challenge

def finish(db, operator, policy, challenge, response_json):
    check_scope(operator, policy)
    if not isinstance(challenge, bytes) or len(challenge) != 32:
        raise ValueError("invalid challenge")
    if not isinstance(response_json, str) or not 0 < len(response_json) <= 65536:
        raise ValueError("invalid registration response")
    row = db.execute(
        "SELECT 1 FROM enrollment_challenges WHERE challenge=? AND operator=? AND expires>?",
        (challenge, operator, int(time.time()))
    ).fetchone()
    if row is None:
        raise ValueError("enrollment challenge unavailable")
    record = verify_enrollment(response_json, challenge, operator, policy)
    register_verified(db, challenge, record)
    return record["id"]
