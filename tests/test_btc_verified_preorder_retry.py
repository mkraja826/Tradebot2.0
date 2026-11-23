"""Evidence-scoped autonomous retry: no broker intent means retry, not order approval."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from tradebot.btc_autonomous_demo import (
    _verified_preorder_retry, prior_fire_receipts_safe)


class VerifiedPreorderRetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/"btc-isolated"
        self.root.mkdir()
        self.p=self.root/"fire-ops.sqlite"
        self.press="a"*32
        self.body={"reason_code":"model_decision_failed",
                   "orders_submitted":False,"protection_verified":False}
        with sqlite3.connect(self.p) as db:
            db.executescript("""CREATE TABLE fire_requests(
                press TEXT,created_at TEXT,status TEXT,result TEXT);
                CREATE TABLE fire_entries(press TEXT);""")
            db.execute("INSERT INTO fire_requests VALUES(?,?,?,?)",(
                self.press,"2026-11-23T14:00:00Z",
                "rejected_no_order",json.dumps(self.body)))

    def test_verified_model_failure_retries_without_authorizing_order(self):
        self.assertTrue(_verified_preorder_retry(self.root,self.press,self.body))
        self.assertTrue(prior_fire_receipts_safe(self.root))

    def test_durable_broker_intent_blocks_retry(self):
        with sqlite3.connect(self.p) as db:
            db.execute("INSERT INTO fire_entries VALUES(?)",(self.press,))
        self.assertFalse(_verified_preorder_retry(self.root,self.press,self.body))
        self.assertFalse(prior_fire_receipts_safe(self.root))

    def test_unknown_reason_and_broker_id_block_retry(self):
        self.assertFalse(_verified_preorder_retry(
            self.root,self.press,{**self.body,"broker_order_id":"123"}))
        self.assertFalse(_verified_preorder_retry(
            self.root,self.press,{**self.body,"reason_code":"broker_unknown"}))
        self.assertFalse(_verified_preorder_retry(
            self.root,self.press,{**self.body,"orders_submitted":True}))

    def test_latest_receipt_evidence_is_required(self):
        self.assertFalse(_verified_preorder_retry(self.root,"b"*32,self.body))
        with sqlite3.connect(self.p) as db:
            db.execute("UPDATE fire_requests SET result=?",(
                json.dumps({**self.body,"reason_code":"execution_unknown"}),))
        self.assertFalse(prior_fire_receipts_safe(self.root))

    def test_unresolved_status_blocks_retry(self):
        with sqlite3.connect(self.p) as db:
            db.execute("UPDATE fire_requests SET status='submitting'")
        self.assertFalse(prior_fire_receipts_safe(self.root))

if __name__=="__main__":
    unittest.main()