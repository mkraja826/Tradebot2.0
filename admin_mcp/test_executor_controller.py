import unittest
import sqlite3
from approval_ledger import initialize
from operator_auth import issue_after_verification
from executor_controller import authorize_fixture

class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        initialize(self.db)
        self.key=b"k"*32
        self.now=1000
        self.request={"id":"a"*32,"action":"restart_service","target":"fixture","arguments":{},"expected_revision":"b"*40,"expires":1100}
        self.state={"revision":"b"*40,"safe_to_restart":True}
        self.envelope=issue_after_verification(self.request,"ab"*32,"fixture",lambda *args:"owner",{"operators":["owner"],"audience":"fixture"},self.key,self.now)
    def run_fixture(self):
        return authorize_fixture(self.request,self.envelope,self.key,self.db,lambda:self.now,["owner"],self.state)
    def test_valid_and_replay(self):
        self.assertEqual(self.run_fixture()["execution_effect"],"none")
        with self.assertRaises(ValueError): self.run_fixture()
    def test_revision_mismatch(self):
        self.state["revision"]="c"*40
        with self.assertRaises(ValueError): self.run_fixture()
        self.state["revision"]="b"*40
        self.assertEqual(self.run_fixture()["status"],"authorized_fixture")
    def test_unsafe_restart(self):
        self.state["safe_to_restart"]=False
        with self.assertRaises(ValueError): self.run_fixture()
    def test_expired_request(self):
        self.now=1100
        with self.assertRaises(ValueError): self.run_fixture()
    def test_forged_signature(self):
        self.envelope["signature"]="0"*64
        with self.assertRaises(ValueError): self.run_fixture()
    def test_modified_request(self):
        self.request["expected_revision"]="c"*40
        self.state["revision"]="c"*40
        with self.assertRaises(ValueError): self.run_fixture()
    def test_arbitrary_arguments(self):
        self.request["arguments"]={"command":"fixture"}
        with self.assertRaises(ValueError): self.run_fixture()
