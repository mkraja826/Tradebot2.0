import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from tradebot.experience_memory_v3 import read_ledger,replay_scorecards,report
from tradebot.fire_reconciliation import reconcile_fire,ReconciliationLedger
from tradebot.ai_replay_v3 import replay,wait_fixture
from tradebot.opportunity_journal_v3 import OpportunityJournal
from test_fire_reconciliation import Broker,NOW as END
from test_opportunity_scanner_v3 import scan,ctx,sig

class ExperienceTests(unittest.TestCase):
    def test_historical_fixture_and_supersession(self):
        with TemporaryDirectory() as d:
            p=Path(d)/"ledger.sqlite"; b=Broker()
            result=reconcile_fire(b,"BTCUSD",b.trade,p,now=END)
            now=int(END.timestamp()*1e6)
            h=read_ledger(p,"BTCUSD",now_us=now)
            self.assertEqual(len(h["records"]),1)
            self.assertEqual(h["records"][0]["net_usd"],"0.075")
            self.assertIsNone(h["records"][0]["entry_efficiency"])
            self.assertEqual(read_ledger(p,"XAUTUSD",now_us=now)["records"],[])
            later=dict(result,is_net_realized_pnl=False,reconciliation_as_of_us=now+1)
            ReconciliationLedger(p).record("BTCUSD:"+b.trade["id"],[],[],later)
            h=read_ledger(p,"BTCUSD",now_us=now+1)
            self.assertEqual(h["records"],[])
            self.assertEqual(h["unverified"],1)
    def test_replay_and_missing_history(self):
        with TemporaryDirectory() as d:
            root=Path(d); j=OpportunityJournal(root/"opportunities-v3.sqlite")
            j.record(scan(),ctx())
            j.record(scan("XAUTUSD",[sig("G01")]),ctx("XAUTUSD"))
            p=root/"ai-replay-v3.sqlite"
            replay(root/"opportunities-v3.sqlite",p,wait_fixture)
            s=replay_scorecards(p)
            self.assertEqual(s["BTCUSD"]["valid"],1)
            self.assertEqual(s["XAUTUSD"]["actions"],{"WAIT":1})
            self.assertIsNone(s["BTCUSD"]["model_quality"])
            r=report(root,root/"missing",now_us=int(END.timestamp()*1e6))
            self.assertEqual(r["markets"]["BTCUSD"]["historical_evidence_status"],"ledger_missing")
            self.assertIsNone(r["markets"]["BTCUSD"]["historical_verified_subset"]["verified_subset_net_usd"])
            self.assertFalse(r["scanner_control"])
            self.assertFalse((root/"missing").exists())
