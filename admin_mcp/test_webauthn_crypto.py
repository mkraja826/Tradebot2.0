import unittest
import importlib.util
import hashlib
import json
import base64
import sqlite3
import time

@unittest.skipUnless(importlib.util.find_spec("webauthn"),"requires dedicated WebAuthn CI")
class CryptoTests(unittest.TestCase):
    def setUp(self):
        import cbor2
        from cryptography.hazmat.primitives.asymmetric import ec
        from passkey_store import CredentialStore
        self.key=ec.generate_private_key(ec.SECP256R1())
        p=self.key.public_key().public_numbers()
        public=cbor2.dumps({1:2,3:-7,-1:1,-2:p.x.to_bytes(32,"big"),-3:p.y.to_bytes(32,"big")})
        self.db=sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.store=CredentialStore(self.db)
        self.db.execute("INSERT INTO credentials VALUES (?,?,?,?)",(b"fixture-id","owner",public,0))
        self.db.commit()
        self.challenge=b"x"*32
        self.store.add_challenge(self.challenge,int(time.time())+60)
        self.policy={"operators":["owner"],"rp_id":"fixture.example","origin":"https://fixture.example"}
    def assertion(self,origin="https://fixture.example",challenge=None,flags=5,forge=False):
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import hashes
        enc=lambda b:base64.urlsafe_b64encode(b).decode().rstrip("=")
        client=json.dumps({"type":"webauthn.get","challenge":enc(challenge or self.challenge),"origin":origin,"crossOrigin":False}).encode()
        auth=hashlib.sha256(b"fixture.example").digest()+bytes([flags])+(1).to_bytes(4,"big")
        key=ec.generate_private_key(ec.SECP256R1()) if forge else self.key
        sig=key.sign(auth+hashlib.sha256(client).digest(),ec.ECDSA(hashes.SHA256()))
        return json.dumps({"id":enc(b"fixture-id"),"rawId":enc(b"fixture-id"),"type":"public-key","response":{"clientDataJSON":enc(client),"authenticatorData":enc(auth),"signature":enc(sig),"userHandle":None},"clientExtensionResults":{}})
    def verify(self,**kwargs):
        from passkey_verify import verify_passkey
        return verify_passkey(self.assertion(**kwargs),self.challenge,self.policy,self.store)
    def test_valid_and_replay(self):
        self.assertEqual(self.verify(),"owner")
        with self.assertRaises(Exception): self.verify()
    def test_forgery(self):
        with self.assertRaises(Exception): self.verify(forge=True)
        self.assertEqual(self.verify(),"owner")
    def test_origin(self):
        with self.assertRaises(Exception): self.verify(origin="https://other.example")
    def test_challenge(self):
        with self.assertRaises(Exception): self.verify(challenge=b"y"*32)
    def test_user_verification(self):
        with self.assertRaises(Exception): self.verify(flags=1)
