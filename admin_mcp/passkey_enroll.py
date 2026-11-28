"""Offline enrollment adapter, not exposed through MCP or public HTTP.
Caller must independently authenticate the provisioning administrator.
"""
from webauthn import verify_registration_response
from webauthn.helpers import parse_registration_credential_json

def verify_enrollment(response_json, challenge, operator, policy):
    if operator not in policy["operators"] or not isinstance(challenge, bytes) or len(challenge)!=32:
        raise ValueError("invalid enrollment scope")
    result=verify_registration_response(
        credential=parse_registration_credential_json(response_json),
        expected_challenge=challenge,
        expected_rp_id=policy["rp_id"],
        expected_origin=policy["origin"],
        require_user_verification=True,
    )
    # Trusted provisioning caller must atomically consume a separate enrollment
    # challenge and insert this credential without replacing existing records.
    return {"id":result.credential_id,"operator":operator,
            "public_key":result.credential_public_key,"sign_count":result.sign_count}
