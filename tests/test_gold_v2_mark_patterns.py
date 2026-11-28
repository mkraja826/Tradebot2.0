import unittest
from unittest.mock import patch
from recover_trading.gold_v2_engine import Bar
from recover_trading.gold_v2_mark_patterns import patterns
from recover_trading.gold_v2_hybrid import preview_mark,MARK_SOURCE
from test_gold_v2_hybrid import reference,ticker,NOW

def bar(i,o,h,l,c):return Bar(i*300,o,h,l,c)
def base():return [bar(i,100,102,98,100) for i in range(1,21)]
def run(b,t=None,h=1,m=1):return patterns(b,t or {},higher=h,mid=m,atr=4)
class MarkPatternTests(unittest.TestCase):
    def test_retest_long(self):
        b=base()+[bar(21,102,105,101,104),bar(22,104,105,102,104)]
        self.assertIn(("mark_breakout_retest",1),run(b))
        self.assertNotIn(("mark_breakout_retest",1),run(b,m=-1))
    def test_retest_short(self):
        b=base()+[bar(21,98,99,95,96),bar(22,96,98,95,96)]
        self.assertIn(("mark_breakout_retest",-1),run(b,h=-1,m=-1))
    def test_range_rejection(self):
        b=base()+[bar(21,100,102,98,100),bar(22,97,101,96,100)]
        self.assertIn(("mark_range_rejection",1),run(b,h=0,m=0))
    def test_rsi_recovery(self):
        b=base()+[bar(21,100,102,98,100),bar(22,100,102,98,100)]
        with patch("recover_trading.gold_v2_mark_patterns.momentum",return_value=25):
            self.assertIn(("mark_rsi_reversal",1),run(b,{"adx":18,"rsi14":32}))
            self.assertNotIn(("mark_rsi_reversal",1),run(b,{"adx":25,"rsi14":32}))
    def test_swing_continuation(self):
        b=base()+[bar(21,100,102,98,100),bar(22,100,104,99,103)]
        t={"adx":30,"plus_di":35,"minus_di":10,"structure":"higher_highs_lows","last_swing_high":102}
        self.assertIn(("mark_swing_continuation",1),run(b,t))
    def test_conflicting_directions_are_separate_hypotheses(self):
        r=reference();report=r.pop("strict_reference_report")
        r.update(signal_source=MARK_SOURCE,mark_report=report)
        report.update(signal_source=MARK_SOURCE,version="gold-v2-mark-model.2",execution_eligible=False,conflicting_directions=True)
        report["candidates"].append(dict(report["candidates"][0],family="mark_range_rejection",direction="SHORT"))
        x=preview_mark(r,ticker(1,100),ticker(2,110),reference_pid=1,demo_pid=2,tick_size=".1",now=NOW)
        self.assertEqual(x["status"],"hypotheses_observed")
        self.assertEqual({p["direction"] for p in x["hypotheses"]},{"LONG","SHORT"})
        self.assertTrue(x["conflicting_directions"])
        self.assertEqual(x["model_version"],"gold-v2-mark-model.2")
        self.assertFalse(x["execution_eligible"])
