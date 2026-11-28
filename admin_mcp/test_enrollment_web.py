import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import provisioning_session as sessions
import enrollment_session_binding as binding
from enrollment_web import application, ORIGIN, HOST, BASE

class EnrollmentWebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "test.db"
        self.policy = {"rp_id":HOST,"origin":ORIGIN,"operators":["alice"],"provisioning_admins":["admin"]}
        db = self.connect()
        db.execute("CREATE TABLE credentials(id BLOB PRIMARY KEY, operator TEXT, public_key BLOB, sign_count INTEGER)")
        sessions.initialize(db)
        binding.initialize(db)
        self.token = sessions.issue(db,"admin",self.policy)
        db.close()
        self.app = application(self.connect,self.policy)
    def tearDown(self):
        self.tmp.cleanup()
    def connect(self):
        return sqlite3.connect(self.path)
    def request(self, action="options", body=None, **overrides):
        raw = json.dumps({"operator":"alice"} if body is None else body).encode()
        env = {"wsgi.url_scheme":"https","HTTP_HOST":HOST,"HTTP_ORIGIN":ORIGIN,
               "REQUEST_METHOD":"POST","PATH_INFO":BASE+"/"+action,
               "HTTP_AUTHORIZATION":"Bearer "+self.token,"CONTENT_TYPE":"application/json",
               "CONTENT_LENGTH":str(len(raw)),"wsgi.input":io.BytesIO(raw)}
        env.update(overrides)
        result = []
        payload = b"".join(self.app(env,lambda status,headers:result.append((status,dict(headers)))))
        return result[0][0],result[0][1],json.loads(payload)
    def test_http(self):
        self.assertEqual(self.request(**{"wsgi.url_scheme":"http"})[0],"403 Forbidden")
    def test_host(self):
        self.assertEqual(self.request(HTTP_HOST="example.org")[0],"403 Forbidden")
    def test_origin(self):
        self.assertEqual(self.request(HTTP_ORIGIN="https://example.org")[0],"403 Forbidden")
    def test_missing_token(self):
        self.assertEqual(self.request(HTTP_AUTHORIZATION="")[0],"403 Forbidden")
    def test_wrong_token(self):
        self.assertEqual(self.request(HTTP_AUTHORIZATION="Bearer "+"0"*64)[0],"403 Forbidden")
    def test_oversized(self):
        self.assertEqual(self.request(CONTENT_LENGTH="131073")[0],"400 Bad Request")
    def test_malformed(self):
        self.assertEqual(self.request(body=[])[0],"400 Bad Request")
    def test_wrong_method(self):
        self.assertEqual(self.request(REQUEST_METHOD="GET")[0],"403 Forbidden")
    @patch("enrollment_atomic.verify_enrollment")
    def test_registration_and_replay(self, verify):
        verify.return_value={"id":b"id","operator":"alice","public_key":b"key","sign_count":0}
        status,headers,options = self.request()
        self.assertEqual(status,"200 OK")
        self.assertEqual(headers["Cache-Control"],"no-store")
        body={"operator":"alice","challenge":options["challenge"],"response":"{}"}
        self.assertEqual(self.request("complete",body)[0],"200 OK")
        self.assertEqual(self.request("complete",body)[0],"403 Forbidden")

if __name__ == "__main__":
    unittest.main()
