import unittest,sqlite3,json
from contextlib import closing
from tempfile import TemporaryDirectory
from pathlib import Path
from decimal import Decimal
from tradebot.m33_index_research_v3 import calculate,record
C=dict(posting_index_consistent=True,uncovered_before_latest_query_us=0,
       overlapping_query_late_ids=0,overlapping_query_missing_ids=0,conflicting_posting_ids=0,
       unclassified_ids=0,capital_posting_ids=0,equity_gaps_over_180s=0)
E=dict(values=[(10,"100"),(20,"120"),(30,"90"),(40,"120"),(50,"150")],through=40)
class IndexResearchTests(unittest.TestCase):
    def test_recovery_does_not_erase_prior_observed_loss(self):
        r=calculate(C,E)
        self.assertEqual(Decimal(r["conditional_index"]),Decimal("1.2"))
        self.assertEqual(Decimal(r["observed_peak_decline"]),0)
        self.assertEqual(Decimal(r["max_observed_decline"]),Decimal("0.25"))
        self.assertEqual(r["sample_count"],4)
        self.assertFalse(r["transfer_adjusted_index_verified"])
    def test_unresolved_conditions(self):
        for k in C:
            r=calculate(dict(C,**{k:1 if k!="posting_index_consistent" else False}),E)
            self.assertIsNone(r["conditional_index"])
            self.assertFalse(r["execution_authorized"])
    def test_unmatched_watermark(self):
        self.assertEqual(calculate(C,dict(E,through=35))["status"],"continuity_unresolved")
    def test_persist_previous_result_on_later_uncertainty(self):
        with TemporaryDirectory() as d:
            p=Path(d)/"index.sqlite"
            a=calculate(C,E);b=calculate(dict(C,capital_posting_ids=1),E)
            self.assertEqual(record(p,"BTCUSD","a"*64,60,a,"fixture-a"),1)
            self.assertEqual(record(p,"BTCUSD","a"*64,60,a,"fixture-a"),1)
            self.assertEqual(record(p,"BTCUSD","a"*64,61,b,"fixture-b"),2)
            with closing(sqlite3.connect(p)) as db:
                rows=db.execute("SELECT body FROM snapshots ORDER BY observed").fetchall()
                self.assertEqual(json.loads(rows[0][0])["result"]["max_observed_decline"],a["max_observed_decline"])
                self.assertIsNone(json.loads(rows[1][0])["result"]["conditional_index"])
                with self.assertRaises(sqlite3.IntegrityError):db.execute("DELETE FROM snapshots")
            with self.assertRaises(ValueError):record(p,"BTCUSD","b"*64,62,b,"fixture-b")
