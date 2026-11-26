import tempfile
import unittest
from pathlib import Path
from recover_trading.gold_entry_intelligence import evidence, plan_economics, report

class GoldEntryIntelligenceTests(unittest.TestCase):
    def context(self):
        return {"symbol":"XAUTUSD","as_of":100,"direction_engine":{"direction":"LONG",
            "regime":{"regime":"trending","trend_bias":"SHORT","volatility":"normal"}},
            "signals":[{"id":"G01","direction":"LONG","closed_at":90},{"id":"G03","direction":"LONG","closed_at":90},
                       {"id":"G12","direction":"SHORT","closed_at":99},{"id":"G09","direction":"LONG","closed_at":101}],
            "demo_account":{"decision_quote":{"status":"fresh_book","timestamp_us":99000000,"best_bid":"3599","best_ask":"3600"}},
            "market":{"frames":{"15m":{"status":"ready","closed_at":99,"features":{"ema50":3500,"ema200":3400}},
                               "1h":{"status":"ready","closed_at":101,"features":{"ema50":1,"ema200":2}}}}}
    def test_point_in_time_and_family_overlap(self):
        card=evidence(self.context(),100)
        self.assertEqual(card["supporting_families"],["trend"])
        self.assertEqual(card["opposing_families"],["reversal"])
        self.assertEqual(card["discarded_signal_records"],1)
        self.assertEqual(card["higher_timeframe_alignment"],"opposed")
        self.assertEqual(card["frames"]["1h"]["status"],"unavailable_or_future")
        self.assertEqual(card["estimated_entry_quote"],"3600")
        self.assertEqual(evidence(self.context(),50)["status"],"invalid_cutoff")
    def test_costs_are_scenarios(self):
        c=self.context();card=evidence(c,100)
        p=plan_economics(c,{"side":"buy","stop_loss":3590,"take_profit":3620},card)
        self.assertTrue(p["orientation_consistent"])
        self.assertEqual(len(p["scenarios"]),3)
        self.assertGreater(p["scenarios"][1]["break_even_win_rate"],1/3)
        self.assertEqual(plan_economics(c,{},card)["status"],"unavailable")
    def test_missing_quote_is_not_fabricated(self):
        c=self.context();c["demo_account"]["decision_quote"]["timestamp_us"]=200000000
        card=evidence(c,100)
        self.assertIsNone(card["estimated_entry_quote"])
        self.assertIsNone(card["spread_bps"])
    def test_no_write_on_missing_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"XAUTUSD"
            self.assertEqual(report(p)["status"],"unavailable")
            self.assertFalse(p.exists())
