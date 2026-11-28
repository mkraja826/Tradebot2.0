import json
import sqlite3
import unittest
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

from recover_trading.gold_v2_entry_qa import explain, record, summary
from recover_trading.gold_v2_engine import Bar
from recover_trading.gold_v2_mark_model import evaluate_mark
from test_gold_v2_mark_model import NOW, frame


class EntryQATests(unittest.TestCase):
    def test_long_short_and_no_candidate(self):
        for low, high, close, expected in [(96, 101, 100.8, "LONG"), (99, 104, 99.2, "SHORT"),
                                           (99, 101, 100, None)]:
            bars = {s: frame(s) for s in (300, 900, 3600)}
            bars[300][-1] = Bar(NOW, 100, high, low, close)
            report = evaluate_mark(bars, {}, [], NOW)
            audit = explain(bars, report)
            self.assertTrue(audit["matches_engine"])
            self.assertEqual(len(audit["setups"]["LONG"]), 6)
            signals = set(audit["engine_candidates"])
            if expected:
                self.assertIn(("mark_range_rejection", expected), signals)
                report["candidates"] = []
                self.assertFalse(explain(bars, report)["matches_engine"])
            else:
                self.assertFalse(signals)

    def test_each_family_matches_model_in_both_directions(self):
        families = ("trend_pullback", "structure_breakout", "breakout_retest",
                    "range_rejection", "rsi_reversal", "swing_continuation")
        for direction, side in (("LONG", 1), ("SHORT", -1)):
            for family in families:
                with self.subTest(direction=direction, family=family):
                    bars = {s: frame(s) for s in (300, 900, 3600)}
                    fast = {"ema": [100, 100-side, 100-2*side, 100-3*side], "atr": 1,
                            "direction": side, "separation_atr": 1, "adx": 30,
                            "plus_di": 20+side, "minus_di": 20-side,
                            "structure": "higher_highs_lows" if side == 1 else "lower_highs_lows",
                            "last_swing_high": 101, "last_swing_low": 99,
                            "rsi14": 35 if side == 1 else 65}
                    prior = 102 if family == "breakout_retest" else 100
                    low, high = (101, 103) if family == "breakout_retest" else (99, 103)
                    if family == "range_rejection":
                        low = 97
                    if family == "rsi_reversal":
                        fast["adx"] = 15
                    def candle(ts, op, hi, lo, cl):
                        prices = [100+side*(p-100) for p in (op, hi, lo, cl)]
                        return Bar(ts, prices[0], max(prices), min(prices), prices[-1])
                    bars[300][-2] = candle(NOW-300, 100, max(prior,101), 99, prior)
                    bars[300][-1] = candle(NOW, max(low,100), high, low, 102)
                    prev_rsi = 30 if side == 1 else 70
                    with patch("recover_trading.gold_v2_mark_model.features", return_value=fast), \
                         patch("recover_trading.gold_v2_mark_patterns.momentum", return_value=prev_rsi), \
                         patch("recover_trading.gold_v2_entry_qa.momentum", return_value=prev_rsi):
                        report = evaluate_mark(bars, {}, [], NOW)
                        audit = explain(bars, report)
                    self.assertIn(("mark_"+family, direction), audit["engine_candidates"])
                    self.assertTrue(audit["matches_engine"])

    def test_journal_retries_missing_data_and_summary(self):
        event = {"timestamp": NOW, "version": "test", "symbol": "XAUTUSD", "errors": {}}
        with TemporaryDirectory() as folder:
            root = Path(folder)
            invalid = evaluate_mark({}, {}, [], NOW)
            record(root, NOW, NOW, event, ({}, invalid))
            bars = {s: frame(s) for s in (300, 900, 3600)}
            report = evaluate_mark(bars, {}, [], NOW)
            for _ in range(2):
                record(root, NOW, NOW+15, event, (bars, report))
            db = root / "entry_qa.sqlite"
            with sqlite3.connect(db) as conn:
                stored = conn.execute("select detail from scans order by started").fetchall()
            self.assertEqual(len(stored), 2)
            self.assertIsNone(json.loads(stored[0][0])["scan"]["matches_engine"])
            self.assertEqual(summary(db, NOW)["totals"], {
                "entry_boundaries_recorded": 1, "no_candidate": 1, "qa_disagreements": 0})
