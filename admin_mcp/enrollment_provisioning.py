"""Trusted provisioning adapter; not a public route.
The host must supply an independently authenticated session verifier.
"""
import base64
import hashlib
from enrollment_controller import begin, finish, check_scope

def encode(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")

class Provisioning:
    def __init__(self, policy, authenticate):
        if not callable(authenticate):
            raise ValueError("administrator authentication required")
        self.policy = policy
        self.authenticate = authenticate

    def authorize(self, session, operator):
        check_scope(operator, self.policy)
        principal = self.authenticate(session)
        if not isinstance(principal, str) or not principal or principal not in self.policy.get("provisioning_admins", ()):
            raise PermissionError("administrator authentication required")

    def options(self, db, session, operator):
        self.authorize(session, operator)
        challenge = begin(db, operator, self.policy)
        return {"challenge": encode(challenge),
                "rp": {"id": self.policy["rp_id"], "name": "Recover Trading"},
                "user": {"id": encode(hashlib.sha256(operator.encode()).digest()),
                         "name": operator, "displayName": operator}}

    def complete(self, db, session, operator, challenge, response_json):
        self.authorize(session, operator)
        return finish(db, operator, self.policy, challenge, response_json)
