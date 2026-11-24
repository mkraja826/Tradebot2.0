import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from tradebot.dispatch_journal_v3 import DispatchJournal
from tradebot.opportunity_journal_v3 import OpportunityJournal
from test_opportunity_scanner_v3 import scan,ctx,sig,NOW
class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        p=Path(self.tmp.name); self.path=p/"dispatch.sqlite"
        j=OpportunityJournal(p/"events.sqlite")
        self.b=j.record(scan(),ctx()); self.g=j.record(scan("XAUTUSD",[sig("G01")]),ctx("XAUTUSD"))
        self.d=DispatchJournal(self.path)
    def test_single_claim_restart(self):
        key=self.b["event_id"]
        self.assertEqual(self.d.stage(self.b,now=NOW),"preview_pending")
        with ThreadPoolExecutor(max_workers=2) as p:
            claims=list(p.map(lambda _:self.d.claim_preview(key,now=NOW),range(2)))
        self.assertEqual(sum(claims),1)
        self.assertEqual(DispatchJournal(self.path).stage(self.b,now=NOW),"preview_reserved")
        self.assertTrue(self.d.finish_preview(key,"synthetic_completed",now=NOW+1))
        self.assertFalse(self.d.claim_preview(key,now=NOW+1))
    def test_timeout_no_retry(self):
        key=self.b["event_id"]; self.d.stage(self.b,now=NOW); self.d.claim_preview(key,now=NOW)
        self.assertEqual(self.d.recover(now=NOW+120)["unknown"],1)
        self.assertEqual(self.d.stage(self.b,now=NOW+120),"preview_unknown")
        self.assertFalse(self.d.claim_preview(key,now=NOW+120))
        self.assertFalse(self.d.finish_preview(key,"synthetic_completed",now=NOW+121))
    def test_expired_and_isolated(self):
        self.assertEqual(self.d.stage(self.b,now=NOW+151),"expired")
        self.assertFalse(self.d.claim_preview(self.b["event_id"],now=NOW+151))
        self.assertEqual(self.d.stage(self.g,now=NOW),"preview_pending")
        self.assertTrue(self.d.claim_preview(self.g["event_id"],now=NOW))
        self.assertTrue(self.d.finish_preview(self.g["event_id"],"blocked_account",now=NOW+1))
        self.assertEqual(self.d.counts(),[("BTCUSD","expired",1),("XAUTUSD","blocked_account",1)])
    def test_tampering(self):
        with self.assertRaises(ValueError): self.d.stage(dict(self.b,context={"symbol":"XAUTUSD"}),now=NOW)
        with self.assertRaises(ValueError): self.d.stage(dict(self.b,execution_authorized=True),now=NOW)
        with self.assertRaises(ValueError): self.d.finish_preview(self.b["event_id"],"executed",now=NOW)
