"""Gateway adapter for an exact, pre-staged Gold demo release."""
import re
import time

from approval_verify import verify
from gateway_core import begin, finish

UNIT = "recover-gold-v2-mark-demo.service"
AUDIENCE = "recover-gold-demo-deploy"


def initialize(db):
    db.execute("""CREATE TABLE IF NOT EXISTS gold_deployments (
        request_id TEXT PRIMARY KEY REFERENCES executions(request_id),
        previous_revision TEXT NOT NULL, release_revision TEXT NOT NULL)""")
    db.commit()


class GoldDeploymentAPI:
    """Queue lookup, operator policy and installed/staged state are host-supplied."""

    def __init__(self, lookup, release_state, store, policy, key, db, clock=time.time):
        self.lookup = lookup
        self.release_state = release_state
        self.store = store
        self.policy = policy
        self.key = key
        self.db = db
        self.clock = clock

    def request(self, request_id):
        if not isinstance(request_id, str) or not re.fullmatch("[0-9a-f]{32}", request_id):
            raise ValueError("invalid request ID")
        record = self.lookup(request_id)
        if not isinstance(record, dict) or record.get("id") != request_id:
            raise ValueError("request unavailable")
        if record.get("action") != "deploy_version" or record.get("status") != "pending_local_approval":
            raise ValueError("pending deployment required")
        args = record.get("arguments")
        if not isinstance(args, dict) or set(args) != {"commit_sha"}:
            raise ValueError("exact release required")
        revision = args["commit_sha"]
        if not isinstance(revision, str) or not re.fullmatch("[0-9a-f]{40}", revision):
            raise ValueError("invalid release")
        previous, staged = self.release_state()
        if not isinstance(previous, str) or not re.fullmatch("[0-9a-f]{40}", previous):
            raise ValueError("installed revision unavailable")
        if revision != staged or previous == revision:
            raise ValueError("tested staged release required")
        return {"id": request_id, "action": "deploy_version", "target": UNIT,
                "expected_revision": previous, "arguments": {"commit_sha": revision}}

    def challenge(self, request_id):
        return begin(self.request(request_id), self.store)

    def approve(self, request_id, nonce, assertion):
        request = self.request(request_id)
        envelope = finish(request, nonce, assertion, self.store, self.policy, self.key)
        return self.reserve(request, envelope)

    def reserve(self, request, envelope):
        if self.db.in_transaction:
            raise ValueError("exclusive transaction required")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if self.request(request["id"]) != request:
                raise ValueError("deployment changed")
            now = int(self.clock())
            claims = verify(request, envelope, self.key, now, AUDIENCE, self.policy["operators"])
            self.db.execute("INSERT INTO consumed VALUES (?,?,?)", (claims["nonce"], claims["digest"], now))
            self.db.execute("INSERT INTO executions(request_id,digest,target,status,started) VALUES (?,?,?,'reserved',?)",
                            (request["id"], claims["digest"], UNIT, now))
            self.db.execute("INSERT INTO gold_deployments VALUES (?,?,?)",
                            (request["id"], request["expected_revision"], request["arguments"]["commit_sha"]))
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return {"request_id": request["id"], "status": "reserved", "execution_effect": "none"}
