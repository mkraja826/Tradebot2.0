"""Both isolated workers: verified no-order provider/risk failures never become exposure."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from tradebot.btc_auto_review import evidence
from tradebot.btc_autonomous_demo import prior_fire_receipts_safe
from tradebot.gold_autonomous_demo import receipts_safe,run_once
from tradebot.btc_no_order_proof import proved_gross_distance_failure

BTC_PRESS="a"*32
GOLD_PRESS="b"*32


class BTCRejectionProofTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/"btc-isolated";self.root.mkdir()
        self.db=self.root/"fire-ops.sqlite"
        self.receipt=dict(reason_code="risk_governor_failed",
            risk_rejection_detail="stop_distance_exceeds_target",
            orders_submitted=False,protection_verified=False,
            direction="SHORT",contracts=7,selected_leverage=20,
            stop_loss="61800",take_profit="60800",
            decision_quote={"best_bid":"61220.0","best_ask":"61220.5"},
            risk_quote_diagnostics={
                "source":"snapshot_vs_signed_broker_quote",
                "broker_entry":"61232","model_entry":"61220.0",
                "quote_change_bps":"1.960143743874550800392030000",
                "model":{"gross_1_to_1_satisfied":False,
                         "stop_distance":"580","target_distance":"420",
                         "gross_reward_risk":"0.7241379310344827586206896552"},
                "broker":{"gross_1_to_1_satisfied":False,
                          "stop_distance":"568","target_distance":"432",
                          "gross_reward_risk":"0.7605633802816901408450704225"}})
        snap={"environment":"delta-india-demo",
              "fire_execution_scope":{"unattended_demo_mode":True},
              "core":{"best_bid":"61220.0","best_ask":"61220.5"}}
        with sqlite3.connect(self.db) as conn:
            conn.executescript("""CREATE TABLE fire_requests(press TEXT,
              created_at TEXT,status TEXT,result TEXT);
              CREATE TABLE fire_model_inputs(press TEXT,snapshot TEXT);
              CREATE TABLE fire_entries(press TEXT);""")
            conn.execute("INSERT INTO fire_model_inputs VALUES(?,?)",
                         (BTC_PRESS,json.dumps(snap)))
            conn.execute("INSERT INTO fire_requests VALUES(?,?,?,?)",
                         (BTC_PRESS,"2026-11-23T19:58:13+00:00",
                          "rejected_no_order",json.dumps(self.receipt)))

    def rewrite(self,detail=None):
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE fire_requests SET result=?",
                       (json.dumps(detail or self.receipt),))

    def test_exact_broker_stop_distance_rejection_can_retry(self):
        self.assertIsNotNone(evidence(self.root))
        self.assertTrue(prior_fire_receipts_safe(self.root))

    def test_unverified_reasons_and_tampering_rejected(self):
        for key,value in (
            ("risk_rejection_detail","unknown_risk"),
            ("broker_order_id","1234"),
            ("orders_submitted",True),
            ("protection_verified",True),
            ("selected_leverage",5),
            ("stop_loss","60900"),
            ("take_profit","60600"),
            ("decision_quote",{"best_bid":"61000","best_ask":"61000.5"}),
        ):
            with self.subTest(key=key):
                self.rewrite({**self.receipt,key:value})
                self.assertIsNone(evidence(self.root))
                self.assertFalse(prior_fire_receipts_safe(self.root))
        self.rewrite()

    def test_model_passes_but_signed_broker_quote_fails(self):
        case=dict(self.receipt)
        case["stop_loss"]="105"
        case["take_profit"]="95"
        case["decision_quote"]={"best_bid":"100","best_ask":"100.1"}
        case["risk_quote_diagnostics"]={
            "source":"snapshot_vs_signed_broker_quote",
            "model_entry":"100","broker_entry":"99",
            "quote_change_bps":"100",
            "model":{"gross_1_to_1_satisfied":True,
                     "stop_distance":"5","target_distance":"5",
                     "gross_reward_risk":"1"},
            "broker":{"gross_1_to_1_satisfied":False,
                      "stop_distance":"6","target_distance":"4",
                      "gross_reward_risk":"0.6666666666666666666666666667"}}
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE fire_model_inputs SET snapshot=?",(
                json.dumps({"environment":"delta-india-demo",
                   "fire_execution_scope":{"unattended_demo_mode":True},
                   "core":{"best_bid":"100","best_ask":"100.1"}}),))
        self.rewrite(case)
        self.assertIsNotNone(evidence(self.root))
        self.assertTrue(prior_fire_receipts_safe(self.root))

    def test_missing_snapshot_or_durable_intent_blocks(self):
        with sqlite3.connect(self.db) as db:
            db.execute("INSERT INTO fire_entries VALUES(?)",(BTC_PRESS,))
        self.assertIsNone(evidence(self.root))
        with sqlite3.connect(self.db) as db:
            db.execute("DELETE FROM fire_entries")
            db.execute("DELETE FROM fire_model_inputs")
        self.assertIsNone(evidence(self.root))


class GoldHTTP500Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/"gold-isolated";self.root.mkdir()
        self.db=self.root/"fire-xaut.sqlite"
        self.receipt=dict(status="rejected_no_order",
                          orders_submitted=False,protection_verified=False,
                          reason_code="provider_http_500")
        with sqlite3.connect(self.db) as db:
            db.executescript("""CREATE TABLE fire_requests(press TEXT,
                created_at TEXT,status TEXT,result TEXT);
                CREATE TABLE fire_entries(press TEXT);""")
            db.execute("INSERT INTO fire_requests VALUES(?,?,?,?)",
                       (GOLD_PRESS,"2026-11-24T00:18:53+00:00",
                        "rejected_no_order",json.dumps(self.receipt)))

    def test_provider_http_500_without_intent_can_retry(self):
        self.assertTrue(receipts_safe(self.root))

    def test_provider_http_500_with_durable_intent_halts(self):
        with sqlite3.connect(self.db) as db:
            db.execute("INSERT INTO fire_entries VALUES(?)",(GOLD_PRESS,))
        self.assertFalse(receipts_safe(self.root))

    def test_provider_http_500_with_broker_id_halts(self):
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE fire_requests SET result=?",
                       (json.dumps({**self.receipt,"broker_order_id":"123"}),))
        self.assertFalse(receipts_safe(self.root))

    def test_unapproved_error_code_halts(self):
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE fire_requests SET result=?",
                       (json.dumps({**self.receipt,"reason_code":"provider_http_401"}),))
        self.assertFalse(receipts_safe(self.root))

    def test_new_provider_http_500_no_order_not_halted(self):
        from datetime import datetime,timezone
        import tradebot.gold_autonomous_demo as gold
        fake=Mock()
        fake.start.return_value=(True,"accepted")
        fake.snapshot.return_value=self.receipt
        result=run_once(self.root,instant=datetime(2026,11,24,4,0,tzinfo=timezone.utc),
             armed=lambda:True,candidate=lambda _:True,
             receipt_check=lambda _:True,active_trade_probe=lambda _:False,
             controller_factory=lambda *a,**k:fake,
             cooldown_check=lambda *a,**k:("ready",0),do_execute=True)
        self.assertEqual(result["result"],"rejected_no_order")
        self.assertFalse((self.root/"gold-auto-demo-halt").exists())

    def test_unknown_or_submitted_execution_halts(self):
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE fire_requests SET result=?",
                       (json.dumps({**self.receipt,"orders_submitted":True}),))
        self.assertFalse(receipts_safe(self.root))

