import unittest
from datetime import datetime,timezone,timedelta
from tradebot.gold_macro_v3 import history,features
from tradebot.gold_strategies_v3 import RULES,evaluate
NOW=datetime(2026,11,24,7,tzinfo=timezone.utc)
T=NOW.timestamp()
def refs():
    days=["2026-11-13","2026-11-16","2026-11-17","2026-11-18","2026-11-19","2026-11-20"]
    def rows(vals): return [{"date":d,"value":v} for d,v in zip(days,vals)]
    return {"broad_dollar":{"status":"ready","observed_at":T-10,"macro_history":{"source":"fred_daily_as_observed","series":{"DTWEXBGS":rows([100,99.9,99.8,99.7,99.6,99])}}},
            "yields":{"status":"ready","observed_at":T-10,"macro_history":{"source":"fred_daily_as_observed","series":{"DGS10":rows([4.2,4.1,4.1,4.1,4.05,4]),"DFII10":rows([2.2,2.1,2.1,2.1,2.05,2])}}}}
class MacroTests(unittest.TestCase):
    def test_parse_excludes_today_future_and_missing(self):
        raw="observation_date,DTWEXBGS\n2026-11-19,100\n2026-11-20,.\n2026-11-23,101\n2026-11-24,99\n2026-11-25,90\n"
        self.assertEqual(history(raw,"broad_dollar",NOW)["DTWEXBGS"],[{"date":"2026-11-19","value":100},{"date":"2026-11-23","value":101}])
    def test_long_short_and_stale(self):
        f=features(refs(),observed_at=T)
        self.assertAlmostEqual(f["broad_dollar_5obs_pct"],-1)
        self.assertAlmostEqual(f["real_yield_5obs_bp"],-20)
        for r in [r for r in RULES if r.id in ("G18","G19")]:
            self.assertEqual(evaluate(r,dict(f,close=12,ema20=11,ema50=10,macd_histogram=1))["directions"],["LONG"])
            self.assertEqual(evaluate(r,dict({k:-v for k,v in f.items()},close=9,ema20=10,ema50=11,macd_histogram=-1))["directions"],["SHORT"])
        self.assertTrue(all(v is None for v in features(refs(),observed_at=T+22201).values()))
    def test_partial_and_future(self):
        r=refs(); r["yields"]["macro_history"]["series"]["DFII10"][-1]["date"]="2026-11-23"
        self.assertIsNone(features(r,observed_at=T)["real_yield_5obs_bp"])
        r["broad_dollar"]["observed_at"]=T+1
        self.assertIsNone(features(r,observed_at=T)["broad_dollar_5obs_pct"])
