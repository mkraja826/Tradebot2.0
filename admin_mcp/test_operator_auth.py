import unittest
from operator_auth import approval_challenge, issue_after_verification
from approval_verify import verify

class OperatorTests(unittest.TestCase):
    def setUp(self):
        self.request={"id":"fixture","action":"test_only","target":"fixture"}
        self.nonce="ab"*32
        self.policy={"operators":["owner"],"audience":"fixture"}
        self.key=b"k"*32
    def test_challenge_binding(self):
        self.assertNotEqual(approval_challenge(self.request,self.nonce),approval_challenge(dict(self.request,target="other"),self.nonce))
    def test_nonce_binding(self):
        self.assertNotEqual(approval_challenge(self.request,self.nonce),approval_challenge(self.request,"cd"*32))
    def test_invalid_nonce(self):
        with self.assertRaises(ValueError):
            approval_challenge(self.request,"invalid")
    def test_unknown_operator(self):
        with self.assertRaises(ValueError):
            issue_after_verification(self.request,self.nonce,"fixture",lambda *args:"other",self.policy,self.key,1000)
    def test_verifier_failure(self):
        def reject(*args):
            raise ValueError("invalid signature")
        with self.assertRaises(ValueError):
            issue_after_verification(self.request,self.nonce,"fixture",reject,self.policy,self.key,1000)
    def test_signed_approval(self):
        envelope=issue_after_verification(self.request,self.nonce,"fixture",lambda *args:"owner",self.policy,self.key,1000)
        claims=verify(self.request,envelope,self.key,1001,"fixture",["owner"])
        self.assertEqual(claims["operator"],"owner")
