"""Development gateway core; no HTTP listener or privileged execution."""
import secrets
import time
from operator_auth import approval_challenge, issue_after_verification

def begin(request, store):
    nonce=secrets.token_hex(32)
    challenge=approval_challenge(request,nonce)
    expires=int(time.time())+120
    store.add_challenge(challenge,expires)
    return {"nonce":nonce,"challenge":challenge.hex(),"expires":expires}

def finish(request, nonce, assertion, store, policy, key):
    # Import only in trusted gateway environment with reviewed dependency.
    from passkey_verify import verify_passkey
    def verifier(response, challenge, trusted_policy):
        return verify_passkey(response,challenge,trusted_policy,store)
    return issue_after_verification(request,nonce,assertion,verifier,policy,key,int(time.time()))
