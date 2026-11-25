import unittest
from recover_trading.backtest import outcome,summarize,replay
from recover_trading.backfill import backfill
from unittest.mock import patch
import tempfile
from pathlib import Path
from tradebot.market_store_v3 import MarketStore

class ReplayTests(unittest.TestCase):
    def test_delayed_entry_and_exact_exit(self):
        at=1800000000
        bars={t:{"time":t,"open":v,"high":v,"low":v,"close":v,"volume":1}
              for t,v in ((at,900),(at+300,100),(at+600,101),(at+900,102),(at+1200,103))}
        r=outcome(bars,at,900,"LONG",15)
        self.assertEqual(r["entry_at"],at+300)
        self.assertAlmostEqual(r["net_bps"],285)
        self.assertAlmostEqual(outcome(bars,at,900,"SHORT",15)["net_bps"],-315)
        del bars[at+600]
        self.assertIsNone(outcome(bars,at,900,"LONG",15))
    def test_empty_and_costed_stats(self):
        self.assertIsNone(summarize([])["win_rate"])
        self.assertEqual(summarize([{"gross_bps":12,"net_bps":-3}])["losses"],1)
    def test_replay_purges_split_and_never_passes_future_data(self):
        start=1800000000; end=start+10800; split=start+5400
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"historical.sqlite"; st=MarketStore(p)
            rows=[{"time":t,"open":100,"high":100,"low":100,"close":100,"volume":1} for t in range(start,end+300,300)]
            st.candles("BTCUSD","5m",rows,as_of=end+300)
            def snap(database,at,*,symbols,candle_as_of):
                self.assertEqual(at,candle_as_of)
                return {"as_of":at,"markets":{"BTCUSD":{"frames":{},"context":{},"quotes":{}}}}
            def scanner(data):
                at=data["as_of"]
                return {"symbol":"BTCUSD","as_of":at,"signals":[{"id":"B01","frame":"5m","direction":"LONG","closed_at":at}],"results":[{"id":"B01","status":"triggered"}]}
            with patch.dict("recover_trading.backtest.SCANNERS",{"BTCUSD":scanner}):
                result=replay(p,"BTCUSD",start,end,stride=300,split=split,make_snapshot=snap)
            self.assertGreater(len(result["events"]),0)
            for event in result["events"]:
                self.assertGreater(event["entry_at"],event["decision_at"])
                self.assertLessEqual(event["exit_at"]+300,split if event["partition"]=="development" else end)
            self.assertGreater(result["counts"]["overlap_excluded"],0)
            self.assertGreater(result["counts"]["boundary_excluded"],0)
