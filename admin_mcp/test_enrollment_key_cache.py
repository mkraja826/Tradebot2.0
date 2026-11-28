import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from enrollment_key_cache import load_keys

class KeyCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        cls.jwk=json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
        cls.jwk.update(kid="first",alg="RS256")
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"keys.json"
        # Simulate the trusted owner for non-root isolated test execution.
        real_fstat=os.fstat
        def owned(fd):
            info=real_fstat(fd)
            from types import SimpleNamespace
            return SimpleNamespace(st_uid=0,st_mode=info.st_mode)
        self.owner=patch("enrollment_key_cache.os.fstat",side_effect=owned)
        self.owner.start()
        self.addCleanup(self.owner.stop)
    def write(self,stamp=100000,keys=None):
        self.path.write_text(json.dumps({"fetched_at":stamp,"jwks":{"keys":keys if keys is not None else [self.jwk]}}))
        self.path.chmod(0o644)
    def load(self):
        return load_keys(self.path,clock=lambda:100000)
    def test_fresh_and_rotation(self):
        self.write()
        self.assertEqual(self.load().keys[0].key_id,"first")
        self.write(keys=[dict(self.jwk,kid="second")])
        self.assertEqual(self.load().keys[0].key_id,"second")
    def test_stale(self):
        self.write(stamp=13599)
        with self.assertRaises(ValueError): self.load()
    def test_future(self):
        self.write(stamp=100001)
        with self.assertRaises(ValueError): self.load()
    def test_missing(self):
        with self.assertRaises(FileNotFoundError): self.load()
    def test_corrupt(self):
        self.path.write_text("invalid")
        with self.assertRaises(ValueError): self.load()
    def test_writable(self):
        self.write()
        self.path.chmod(0o666)
        with self.assertRaises(ValueError): self.load()
    def test_symlink(self):
        self.write()
        target=self.path.with_name("target")
        self.path.rename(target)
        self.path.symlink_to(target)
        with self.assertRaises(OSError): self.load()
    def test_duplicate(self):
        self.write(keys=[self.jwk,self.jwk])
        with self.assertRaises(ValueError): self.load()
    def test_wrong_owner(self):
        self.write()
        from types import SimpleNamespace
        with patch("enrollment_key_cache.os.fstat",return_value=SimpleNamespace(st_uid=1234,st_mode=0o100644)):
            with self.assertRaises(ValueError): self.load()
