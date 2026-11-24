import unittest,sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import closing
from tradebot.commissioning_v3 import verify_events,audit,ro
from tradebot.opportunity_journal_v3 import OpportunityJournal
from test_opportunity_scanner_v3 import scan,ctx,sig,NOW

class CommissioningTests(unittest.TestCase):
    def test_replay_and_index_tamper(self):
        with TemporaryDirectory() as d:
            p=Path(d)/"opportunities-v3.sqlite"
            j=OpportunityJournal(p)
            j.record(scan(),ctx())
            j.record(scan("XAUTUSD",[sig("G01")]),ctx("XAUTUSD"))
            with closing(ro(p)) as db:
                self.assertEqual(verify_events(db),{"events":2,"signals":2,"synthetic_wait_replays":2})
            with closing(sqlite3.connect(p)) as db,db: db.execute("DELETE FROM seen WHERE symbol='BTCUSD'")
            with closing(ro(p)) as db:
                with self.assertRaises(ValueError): verify_events(db)
    def test_missing_sources(self):
        with TemporaryDirectory() as d:
            r=audit(d,now=NOW)
            self.assertFalse(r["research_checks_passed"])
            self.assertFalse(r["execution_authorized"])
            self.assertFalse(r["live_ai_verified"])
            self.assertEqual(r["paid_ai_requests"],0)
            self.assertEqual(r["journal_audit"]["status"],"failed")
            self.assertFalse((Path(d)/"opportunities-v3.sqlite").exists())
