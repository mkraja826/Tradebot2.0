"""Development adapter; requires a separately installed and reviewed webauthn dependency.
Only callable inside the trusted gateway, never as an MCP tool.
"""
from webauthn import verify_authentication_response
from webauthn.helpers import parse_authentication_credential_json

def verify_passkey(assertion_json, challenge, policy, credential_store):
    credential = parse_authentication_credential_json(assertion_json)
    record = credential_store.lookup(credential.raw_id)
    if record is None or record.operator not in policy["operators"]:
        raise ValueError("unknown credential")
    result = verify_authentication_response(
        credential=credential,
        expected_challenge=challenge,
        expected_rp_id=policy["rp_id"],
        expected_origin=policy["origin"],
        credential_public_key=record.public_key,
        credential_current_sign_count=record.sign_count,
        require_user_verification=True,
    )
    # Store must atomically compare the old counter and consume the challenge.
    if not credential_store.consume_verified_challenge(
        challenge, credential.raw_id, record.sign_count, result.new_sign_count
    ):
        raise ValueError("challenge consumed or credential changed")
    return record.operator
