import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from contextlib import closing
import sqlite3
from tradebot.shadow_dispatch_v3 import tick
from tradebot.opportunity_journal_v3 import OpportunityJournal
from tradebot.dispatch_journal_v3 import DispatchJournal
from test_opportunity_scanner_v3 import scan,ctx,sig,NOW
class ShadowDispatchTests(unittest.TestCase):
    def test_both_routes_exactly_once(self):
        with TemporaryDirectory() as d:
            p=Path(d); j=OpportunityJournal(p/"opportunities-v3.sqlite")
            j.record(scan(),ctx()); j.record(scan("XAUTUSD",[sig("G01")]),ctx("XAUTUSD"))
            r=tick(p,now=NOW)
            self.assertTrue(all(x["synthetic_completed"]==1 for x in r["markets"].values()))
            self.assertEqual(r["paid_ai_requests"],0); self.assertEqual(r["orders_submitted"],0)
            self.assertFalse(r["execution_authorized"])
            r=tick(p,now=NOW+1)
            self.assertTrue(all(x["duplicate_or_terminal"]==1 for x in r["markets"].values()))
            with closing(sqlite3.connect(p/"shadow-decisions-v3.sqlite")) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM decisions").fetchone()[0],2)
    def test_expired_and_interrupted(self):
        with TemporaryDirectory() as d:
            p=Path(d); j=OpportunityJournal(p/"opportunities-v3.sqlite")
            e=j.record(scan(),ctx()); j.record(scan("XAUTUSD",[sig("G01")]),ctx("XAUTUSD"))
            dj=DispatchJournal(p/"dispatch-preview-v3.sqlite")
            dj.stage(e,now=NOW); self.assertTrue(dj.claim_preview(e["event_id"],now=NOW))
            r=tick(p,now=NOW+151)
            self.assertEqual(r["recovery"]["unknown"],1)
            self.assertTrue(all(x["fresh_candidates"]==0 for x in r["markets"].values()))
            self.assertFalse((p/"shadow-decisions-v3.sqlite").exists())
