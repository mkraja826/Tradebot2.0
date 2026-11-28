"""Offline API boundary. No HTTP listener, live queue access or privileged actions."""
import re
from gateway_core import begin, finish

class FixtureAPI:
    def __init__(self, requests, store, policy, key):
        self.requests=requests
        self.store=store
        self.policy=policy
        self.key=key

    def request(self, request_id):
        if not isinstance(request_id,str) or not re.fullmatch("[0-9a-f]{32}",request_id):
            raise ValueError("invalid request ID")
        record=self.requests.get(request_id)
        if not isinstance(record,dict) or set(record)!={"id","action","target"}:
            raise ValueError("request unavailable")
        if record["id"]!=request_id or record["action"]!="test_only" or record["target"]!="fixture":
            raise ValueError("request unavailable")
        return dict(record)

    def challenge(self, request_id):
        return begin(self.request(request_id),self.store)

    def approve(self, request_id, nonce, assertion):
        if not isinstance(assertion,str) or len(assertion)>32768:
            raise ValueError("invalid assertion")
        return finish(self.request(request_id),nonce,assertion,self.store,self.policy,self.key)
