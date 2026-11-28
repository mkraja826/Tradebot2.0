import unittest
import hashlib
import hmac
from approval_verify import canonical, request_digest, verify

class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.key = b"test-only-key"*4
        self.request = {"id":"test","action":"test_only","target":"fixture"}
        self.claims = {"digest":request_digest(self.request),"audience":"fixture","operator":"operator","issued":100,"expires":200,"nonce":"a"*32}
    def envelope(self):
        return {"claims":dict(self.claims),"signature":hmac.new(self.key,canonical(self.claims),hashlib.sha256).hexdigest()}
    def check(self, request=None, envelope=None, now=150):
        return verify(self.request if request is None else request,self.envelope() if envelope is None else envelope,self.key,now,"fixture",{"operator"})
    def test_valid(self):
        self.assertEqual(self.check()["operator"],"operator")
    def test_modified_request(self):
        with self.assertRaises(ValueError):
            self.check(request={"id":"different"})
    def test_expired(self):
        with self.assertRaises(ValueError):
            self.check(now=200)
    def test_forged(self):
        e=self.envelope()
        e["signature"]="0"*64
        with self.assertRaises(ValueError):
            self.check(envelope=e)
    def test_wrong_audience(self):
        self.claims["audience"]="other"
        with self.assertRaises(ValueError):
            self.check()
    def test_wrong_operator(self):
        self.claims["operator"]="other"
        with self.assertRaises(ValueError):
            self.check()
    def test_future_approval(self):
        with self.assertRaises(ValueError):
            self.check(now=99)
    def test_excessive_lifetime(self):
        self.claims["expires"]=1000
        with self.assertRaises(ValueError):
            self.check()
