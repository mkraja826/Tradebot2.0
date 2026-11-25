import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from recover_trading.department_feedback import packet, attach, copy_to_context

class DepartmentFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"learning.sqlite"
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE lessons(symbol TEXT,decision_id TEXT,closed TEXT,enrolled INTEGER,payload TEXT)")
    def add(self,symbol="BTCUSD",ident="a"*64,enrolled=200,closed="1970-01-01T00:02:00Z",net="-3",**extra):
        d={"symbol":symbol,"decision_id":ident,"closed":closed,"direction":"SHORT",
           "active_rules":["B01","G01","untrusted text"],"learning_status":"observation_only",
           "execution_effect":"none","net_before_funding":net,**extra}
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO lessons VALUES(?,?,?,?,?)",(symbol,ident,closed,enrolled,json.dumps(d)))
    def test_prior_facts_only(self):
        self.add()
        self.add(symbol="XAUTUSD",ident="b"*64)
        self.add(ident="c"*64,enrolled=300)
        self.add(ident="d"*64,closed="1970-01-01T00:05:00Z")
        self.add(ident="e"*64,net="NaN")
        self.add(ident="f"*64,learning_status="unverified")
        p=packet(self.path,"BTCUSD",300)
        self.assertEqual(len(p["observations"]),1)
        self.assertEqual(p["observations"][0]["active_rules"],["B01"])
        self.assertEqual(p["observations"][0]["outcome"],"loss")
        self.assertEqual(p["validated_lessons"],[])
        self.assertFalse(p["causal_validation"])
    def test_no_db_creation_and_no_gate(self):
        path=self.path.parent/"missing.sqlite"
        report={"symbol":"BTCUSD","as_of":300,"signals":[1]}
        r=attach(report,path)
        self.assertEqual(r["signals"],[1])
        self.assertEqual(r["department_learning"]["status"],"unavailable")
        self.assertFalse(path.exists())
        self.assertIs(attach(report,None),report)
    def test_entry_and_management_context_contract(self):
        self.add()
        r=attach({"symbol":"BTCUSD","as_of":300},self.path)
        for ctx in ({"symbol":"BTCUSD","as_of":300,"demo_account":{}},
                    {"symbol":"BTCUSD","as_of":300,"position":{}}):
            self.assertEqual(copy_to_context(r,ctx)["department_learning"],r["department_learning"])
        self.assertNotIn("department_learning",copy_to_context(r,{"symbol":"XAUTUSD","as_of":300}))
        self.assertNotIn("department_learning",copy_to_context(r,{"symbol":"BTCUSD","as_of":301}))
