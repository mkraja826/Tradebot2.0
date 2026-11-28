import json
import time
import unittest
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from enrollment_ingress import protect

class IngressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537,key_size=2048)
        cls.other = rsa.generate_private_key(public_exponent=65537,key_size=2048)
        cls.issuer = "https://example.cloudflareaccess.com"
        cls.audience = "enrollment-test"
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        jwk.update(kid="test",alg="RS256")
        def backend(env,start):
            start("200 OK",[])
            return [env["wsgi.url_scheme"].encode()]
        cls.app = staticmethod(protect(backend,cls.issuer,cls.audience,{"keys":[jwk]},["operator-test"]))
    def token(self,key=None,kid="test",**overrides):
        now=int(time.time())
        claims={"iss":self.issuer,"aud":self.audience,"sub":"operator-test","iat":now,"exp":now+120}
        claims.update(overrides)
        return jwt.encode(claims,key or self.key,algorithm="RS256",headers={"kid":kid})
    def request(self,token="",peer="127.0.0.1"):
        result=[]
        body=b"".join(self.app({"REMOTE_ADDR":peer,"HTTP_CF_ACCESS_JWT_ASSERTION":token,"wsgi.url_scheme":"http"},lambda status,headers:result.append(status)))
        return result[0],body
    def test_valid(self):
        self.assertEqual(self.request(self.token()),("200 OK",b"https"))
    def test_missing(self):
        self.assertEqual(self.request()[0],"403 Forbidden")
    def test_forged(self):
        self.assertEqual(self.request(self.token(key=self.other))[0],"403 Forbidden")
    def test_expired(self):
        self.assertEqual(self.request(self.token(exp=int(time.time())-1))[0],"403 Forbidden")
    def test_subject(self):
        self.assertEqual(self.request(self.token(sub="other"))[0],"403 Forbidden")
    def test_audience(self):
        self.assertEqual(self.request(self.token(aud="other"))[0],"403 Forbidden")
    def test_issuer(self):
        self.assertEqual(self.request(self.token(iss="https://other.cloudflareaccess.com"))[0],"403 Forbidden")
    def test_unknown_key(self):
        self.assertEqual(self.request(self.token(kid="unknown"))[0],"403 Forbidden")
    def test_nonlocal_peer(self):
        self.assertEqual(self.request(self.token(),peer="192.0.2.1")[0],"403 Forbidden")
