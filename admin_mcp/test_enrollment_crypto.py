import base64
import hashlib
import json
import os
import unittest
import cbor2
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes
from passkey_enroll import verify_enrollment

def enc(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

class RealWebAuthn(unittest.TestCase):
    def setUp(self):
        self.policy={"rp_id":"tradingbot.micirql.com","origin":"https://tradingbot.micirql.com","operators":["alice"]}
        self.challenge=os.urandom(32)
        self.key=ec.generate_private_key(ec.SECP256R1())
        self.cid=os.urandom(32)
    def credential(self, origin=None, challenge=None, flags=0x45, tamper=False):
        client=json.dumps({"type":"webauthn.create","challenge":enc(challenge or self.challenge),"origin":origin or self.policy["origin"],"crossOrigin":False}).encode()
        p=self.key.public_key().public_numbers()
        cose=cbor2.dumps({1:2,3:-7,-1:1,-2:p.x.to_bytes(32,"big"),-3:p.y.to_bytes(32,"big")})
        auth=hashlib.sha256(self.policy["rp_id"].encode()).digest()+bytes([flags])+bytes(4)+bytes(16)+len(self.cid).to_bytes(2,"big")+self.cid+cose
        sig=self.key.sign(auth+hashlib.sha256(client).digest(),ec.ECDSA(hashes.SHA256()))
        if tamper:
            sig=sig[:-1]+bytes([sig[-1]^1])
        att=cbor2.dumps({"fmt":"packed","authData":auth,"attStmt":{"alg":-7,"sig":sig}})
        return json.dumps({"id":enc(self.cid),"rawId":enc(self.cid),"type":"public-key","response":{"clientDataJSON":enc(client),"attestationObject":enc(att)},"clientExtensionResults":{}})
    def verify(self, **kwargs):
        return verify_enrollment(self.credential(**kwargs),self.challenge,"alice",self.policy)
    def test_valid(self):
        self.assertEqual(self.verify()["id"],self.cid)
    def test_wrong_challenge(self):
        with self.assertRaises(Exception):
            self.verify(challenge=os.urandom(32))
    def test_wrong_origin(self):
        with self.assertRaises(Exception):
            self.verify(origin="https://example.org")
    def test_missing_user_verification(self):
        with self.assertRaises(Exception):
            self.verify(flags=0x41)
    def test_invalid_signature(self):
        with self.assertRaises(Exception):
            self.verify(tamper=True)

if __name__=="__main__":
    unittest.main()
