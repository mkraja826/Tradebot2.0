from contextlib import closing
import unittest,json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from tradebot.strategy_profiles_v3 import build
from tradebot.decision_learning_context_v3 import freeze
from tradebot.opportunity_scanner_v3 import tick
from tradebot.opportunity_journal_v3 import digest
from tradebot.ai_decision_v3 import prepare,validate
from tradebot.ai_replay_v3 import wait_fixture
from test_opportunity_scanner_v3 import NOW,sig,scan
import sqlite3
class DecisionLearningTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.root=Path(self.tmp.name)
        self.report=build(self.root,{"BTCUSD":[],"XAUTUSD":[]},now=NOW,coverage_by_market={"BTCUSD":{},"XAUTUSD":{}})
        self.p=self.root/"strategy-profiles-v3.json"
        self.context={"symbol":"BTCUSD","context_observed_at":NOW,"market":{"frames":{}}}
    def save(self): self.p.write_text(json.dumps(self.report))
    def test_scope_and_age(self):
        self.save()
        a=freeze(self.root,"BTCUSD",[sig(),sig("G01")],self.context,now=NOW)
        self.assertEqual([x["rule_id"] for x in a["profiles"]],["B01"])
        self.assertEqual(a["omitted_signal_groups"],1)
        self.assertEqual(a["source_report_sha256"],digest(self.report))
        for t in (NOW+1,NOW-661):
            self.report["checked_at"]=t; self.save()
            self.assertEqual(freeze(self.root,"BTCUSD",[sig()],self.context,now=NOW)["status"],"unavailable")
    def test_scanner_freezes_and_missing_never_blocks(self):
        for i in range(2):
            stamp=NOW+i*300
            (self.root/"collector-status.json").write_text(json.dumps({"as_of":stamp}))
            if i==0: self.save()
            else: self.p.write_text("malformed")
            def fake_snapshot(db,t,symbols):
                return {"as_of":t,"markets":{symbols[0]:{"context":{},"frames":{}}}}
            def btc(s):
                return dict(scan(stamp=stamp,signals=[sig(stamp=stamp)]),results=[],deferred={},trigger_ai=True)
            with patch("tradebot.opportunity_scanner_v3.snapshot",fake_snapshot),patch("tradebot.opportunity_scanner_v3.SCANNERS",{"BTCUSD":btc}):
                r=tick(self.root,now=stamp)
            self.assertEqual(r["status"],"ready")
            with closing(sqlite3.connect(self.root/"opportunities-v3.sqlite")) as db, db:
                e=json.loads(db.execute("select payload from events where as_of=?",(stamp,)).fetchone()[0])
            a=e["context"]["strategy_learning"]
            self.assertEqual(a["status"],"research_advisory" if i==0 else "unavailable")
            q=prepare(e); self.assertEqual(q["payload"]["context"]["strategy_learning"],a)
            self.assertEqual(validate(wait_fixture(q),q)["action"],"WAIT")
            self.assertFalse(q["execution_authorized"])
            self.assertEqual(digest(q["payload"]),q["request_sha256"])
