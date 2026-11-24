import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from tradebot.ai_decision_v3 import prepare,validate
from tradebot.ai_replay_v3 import replay,wait_fixture
from tradebot.opportunity_journal_v3 import OpportunityJournal
from test_opportunity_scanner_v3 import scan,ctx,sig
class AIDecisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.j=OpportunityJournal(self.root/"events.sqlite")
        self.b=self.j.record(scan(),ctx())
        self.g=self.j.record(scan("XAUTUSD",[sig("G01")]),ctx("XAUTUSD"))
    def request(self,event):
        return prepare(event,{"symbol":event["symbol"],"mode":"synthetic_fixture"})
    def reply(self,req,side):
        r=wait_fixture(req)
        r.update(action=side,rationale="Synthetic test only",plan=dict(entry_type="MARKET",entry_reference=100,contracts=1,leverage=2,margin_quote=50,stop_loss=95 if side=="LONG" else 105,take_profit=105 if side=="LONG" else 95,holding_minutes=15,management="Synthetic exit test"))
        return r
    def test_routes_and_actions(self):
        for event,model in ((self.b,"GPT-6.1 Sol"),(self.g,"DeepSeek")):
            r=self.request(event); self.assertEqual(r["model_if_enabled"],model)
            for side in ("LONG","SHORT"):
                self.assertEqual(validate(self.reply(r,side),r)["action"],side)
            self.assertEqual(validate(wait_fixture(r),r)["action"],"WAIT")
            self.assertFalse(r["execution_authorized"])
    def test_no_account_and_cross_market(self):
        r=prepare(self.b)
        with self.assertRaises(ValueError): validate(self.reply(r,"LONG"),r)
        with self.assertRaises(ValueError): validate(wait_fixture(prepare(self.g)),r)
        with self.assertRaises(ValueError): prepare(self.b,{"symbol":"XAUTUSD","mode":"synthetic_fixture"})
    def test_bad_contract_and_geometry(self):
        req=self.request(self.b)
        for k,v in (("contracts",1.5),("leverage",float("nan")),("stop_loss",110),("margin_quote",-1),("holding_minutes",True)):
            r=self.reply(req,"LONG"); r["plan"][k]=v
            with self.assertRaises(ValueError): validate(r,req)
    def test_context_tamper(self):
        with self.assertRaises(ValueError): prepare({**self.b,"context":dict(self.b["context"],bad=True)})
    def test_persistent_replay(self):
        target=self.root/"replays.sqlite"
        self.assertEqual(replay(self.j.path,target,wait_fixture)["new"],2)
        self.assertEqual(replay(self.j.path,target,wait_fixture)["duplicate"],2)
