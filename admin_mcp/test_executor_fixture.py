import hashlib
import hmac
import sqlite3
import unittest
from approval_verify import canonical, request_digest
from approval_ledger import initialize
from executor_fixture import execute_fixture

class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        initialize(self.db)
        self.key=b"fixture-only-key"*4
        self.request={"id":"one","action":"test_only","target":"fixture"}
    def envelope(self, request):
        claims={"digest":request_digest(request),"audience":"fixture","operator":"operator","issued":100,"expires":200,"nonce":"a"*32}
        return {"claims":claims,"signature":hmac.new(self.key,canonical(claims),hashlib.sha256).hexdigest()}
    def execute(self, request, envelope):
        return execute_fixture(self.db,request,envelope,self.key,150,{"operator"})
    def test_valid_and_replay(self):
        e=self.envelope(self.request)
        self.assertEqual(self.execute(self.request,e)["execution_effect"],"none")
        with self.assertRaises(ValueError):
            self.execute(self.request,e)
    def test_forgery(self):
        e=self.envelope(self.request)
        e["signature"]="0"*64
        with self.assertRaises(ValueError):
            self.execute(self.request,e)
        self.assertEqual(self.db.execute("SELECT count(*) FROM consumed").fetchone()[0],0)
    def test_unallowed_action(self):
        r=dict(self.request,action="restart_service")
        with self.assertRaises(ValueError):
            self.execute(r,self.envelope(r))
    def test_modified_request(self):
        with self.assertRaises(ValueError):
            self.execute(dict(self.request,id="two"),self.envelope(self.request))
