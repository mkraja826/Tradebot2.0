import unittest,sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from tradebot.m33_policy_candidate_v3 import replay,append
from test_m25_equity_policy_research_v3 import val,flow
S="BTCUSD";I="synthetic-btc"
class CandidateTests(unittest.TestCase):
    def test_preserve_breach_after_deposit_and_recovery(self):
        r=replay(S,I,[val(1,"100"),val(2,"90"),flow(3,"90","190","100"),val(4,"220")])
        self.assertEqual(r["observed_breach_history"],["daily","sampled_drawdown","weekly"])
        self.assertEqual(r["last_known_max_sampled_decline"],"0.1")
        self.assertFalse(r["execution_authorized"])
    def test_unmatched_transfer_stops_index(self):
        r=replay(S,I,[val(1,"100"),val(2,"90"),flow(3,"90","190","99"),val(4,"220")])
        self.assertEqual(r["status"],"continuity_unresolved")
        self.assertEqual(r["last_known_index"],"0.9")
        self.assertIn("daily",r["observed_breach_history"])
    def test_gap_and_missing_opening(self):
        r=replay(S,I,[val(400,"100"),val(401,"90"),val(600,"110")])
        self.assertFalse(r["weekly_opening_observed"])
        self.assertIn("observation_gap",r["uncertainty"])
        self.assertEqual(r["last_known_index"],"0.9")
    def test_exact_transfer(self):
        r=replay(S,I,[val(1,"100"),flow(2,"100","50","-50"),val(3,"50")])
        self.assertEqual(r["last_known_index"],"1")
        self.assertEqual(r["observed_breach_history"],[])
    def test_restart_and_duplicate(self):
        with TemporaryDirectory() as d:
            p=Path(d)/"synthetic-policy.sqlite"
            append(p,S,I,val(1,"100"))
            a=append(p,S,I,val(2,"90"))
            self.assertEqual(a,append(p,S,I,val(2,"90")))
            b=append(p,S,I,dict(val(3,"90"),kind="unknown"))
            self.assertEqual(a["observed_breach_history"],b["observed_breach_history"])
            with closing(sqlite3.connect(p)) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM fixture_events").fetchone()[0],3)
                with self.assertRaises(sqlite3.IntegrityError):db.execute("DELETE FROM fixture_events")
            with self.assertRaises(ValueError):append(p,S,I,val(2,"90"))
    def test_scope(self):
        with self.assertRaises(ValueError):replay(S,"live",[val(1,"100")])
