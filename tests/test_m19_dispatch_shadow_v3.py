from contextlib import closing
import unittest,sqlite3
from tempfile import TemporaryDirectory
from pathlib import Path
from tradebot.m19_dispatch_shadow_v3 import tick,prepare_preview
from tradebot.opportunity_journal_v3 import OpportunityJournal
from tradebot.product_context_v3 import product_spec
from test_model_wire_v3 import scan,ctx,sig,raw,NOW
class DispatchTests(unittest.TestCase):
    def test_both_routes_and_dedup(self):
        with TemporaryDirectory() as d:
            j=OpportunityJournal(Path(d)/"opportunities-v3.sqlite")
            specs={}
            for s,r in (("BTCUSD","B01"),("XAUTUSD","G01")):
                e=j.record(scan(s,[sig(r)]),ctx(s))
                specs[s]={"status":"ready","data":product_spec(raw(s),s,NOW)}
                p=prepare_preview(e,specs[s]["data"],now=NOW)
                self.assertEqual(p["signal_count"],1)
                self.assertFalse(p["execution_authorized"])
                with self.assertRaises(ValueError):prepare_preview(e,specs[s]["data"],now=NOW+151)
            for expected in ("rehearsed","duplicates"):
                r=tick(d,spec_reader=lambda:specs,clock=lambda:NOW)
                self.assertEqual(r["paid_ai_requests"],0)
                self.assertEqual(r["markets"]["BTCUSD"]["interface"],"messages")
                self.assertEqual(r["markets"]["XAUTUSD"]["interface"],"chat_completions")
                for s in specs:self.assertEqual(r["markets"][s][expected],1)
            with closing(sqlite3.connect(Path(d)/"m19-dispatch-shadow-v3.sqlite")) as db, db:
                self.assertEqual(db.execute("SELECT count(*) FROM previews").fetchone()[0],2)
