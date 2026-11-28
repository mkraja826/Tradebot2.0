import io
import json
import unittest
from gateway_http import application

class FakeAPI:
    def request(self,rid):
        return {"id":rid,"action":"test_only","target":"fixture"}
    def challenge(self,rid):
        return {"nonce":"a"*64,"challenge":"ab"*32,"expires":123}
    def approve(self,rid,nonce,assertion):
        if assertion!="fixture": raise ValueError("invalid")
        return {"signature":"never expose"}

class TransportTests(unittest.TestCase):
    def call(self,action,body=None,**overrides):
        raw=json.dumps({} if body is None else body).encode()
        env={"wsgi.url_scheme":"https","HTTP_ORIGIN":"https://fixture.example","REQUEST_METHOD":"POST","CONTENT_TYPE":"application/json","PATH_INFO":"/fixture/"+"a"*32+"/"+action,"CONTENT_LENGTH":str(len(raw)),"wsgi.input":io.BytesIO(raw)}
        env.update(overrides)
        status=[]
        app=application(FakeAPI(),"https://fixture.example","fixture.example",[b"id"])
        result=json.loads(b"".join(app(env,lambda s,h:status.append(s))))
        return status[0],result
    def test_request(self):
        self.assertEqual(self.call("request")[1]["action"],"test_only")
    def test_origin(self):
        self.assertTrue(self.call("request",HTTP_ORIGIN="https://other.example")[0].startswith("403"))
    def test_tls(self):
        self.assertTrue(self.call("request",**{"wsgi.url_scheme":"http"})[0].startswith("403"))
    def test_challenge_encoding(self):
        self.assertEqual(len(self.call("challenge")[1]["challenge"]),43)
    def test_approval_no_signature(self):
        self.assertEqual(self.call("approve",{"nonce":"a"*64,"assertion":"fixture"})[1],{"status":"fixture_verified","execution_effect":"none"})
    def test_invalid_assertion(self):
        self.assertTrue(self.call("approve",{"nonce":"a"*64,"assertion":"bad"})[0].startswith("400"))
    def test_size_limit(self):
        self.assertTrue(self.call("request",CONTENT_LENGTH="65537")[0].startswith("400"))
