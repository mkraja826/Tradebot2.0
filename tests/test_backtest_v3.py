import unittest,sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import closing
from tradebot.backtest_v3 import outcome,summarize,replay
from tradebot.market_store_v3 import MarketStore
NOW=1800000000
class BacktestTests(unittest.TestCase):
    def test_future_only_cost_and_gap(self):
        with TemporaryDirectory() as d:
            p=Path(d)/"market.sqlite"; m=MarketStore(p)
            bars=[dict(time=NOW+300*i,open=100,high=103,low=99,close=102,volume=1) for i in range(4)]
            bars[0].update(open=99,close=99,low=98)
            m.candles("BTCUSD","5m",bars,as_of=NOW+1200)
            with closing(sqlite3.connect(p)) as db:
                r=outcome(db,"BTCUSD",NOW,"LONG")
                self.assertEqual(r["entry_at"],NOW+300)
                self.assertAlmostEqual(r["net_cost_scenario_pct"],1.9)
                self.assertAlmostEqual(outcome(db,"BTCUSD",NOW,"SHORT")["net_cost_scenario_pct"],-2.1)
                self.assertIsNone(outcome(db,"BTCUSD",NOW+300,"LONG"))
    def test_sequence_drawdown_and_empty(self):
        r=summarize([{"net_cost_scenario_pct":x} for x in (2,-1,-2,1)])
        self.assertEqual(r["additive_sequence_drawdown_pct_points"],3)
        self.assertEqual(r["positive_after_cost"],2)
        self.assertIsNone(summarize([])["mean_after_cost_pct"])
    def test_invalid_cutoff(self):
        with self.assertRaises(ValueError): replay("missing",start=NOW,end=NOW+300,cutoff=NOW)
