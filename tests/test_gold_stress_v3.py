import unittest
from datetime import datetime,timezone
from tradebot.gold_stress_v3 import parse,features
from tradebot.gold_strategies_v3 import RULES,evaluate
NOW=datetime(2026,11,24,7,tzinfo=timezone.utc)
T=NOW.timestamp()
class StressTests(unittest.TestCase):
    def refs(self):
        v="observation_date,VIXCLS\n2026-11-13,19\n2026-11-16,20\n2026-11-17,21\n2026-11-18,24\n2026-11-19,27\n2026-11-20,35\n2026-11-24,100\n"
        s="observation_date,STLFSI4\n2026-11-06,0.1\n2026-11-13,0.4\n"
        return {k:dict(status="ready",observed_at=T-1,data=parse(raw,k,NOW)) for k,raw in (("market_vix",v),("financial_stress",s))}
    def test_long_short(self):
        f=features(self.refs(),observed_at=T)
        self.assertEqual(f["vix_daily"],35)
        self.assertEqual(f["vix_5obs_change"],16)
        r=next(r for r in RULES if r.id=="G23")
        self.assertEqual(evaluate(r,dict(f,close=12,ema20=11,ema50=10,macd_histogram=1))["directions"],["LONG"])
        self.assertEqual(evaluate(r,dict(vix_daily=15,vix_5obs_change=-4,stress_weekly=-.4,stress_weekly_change=-.2,close=9,ema20=10,ema50=11,macd_histogram=-1))["directions"],["SHORT"])
        self.assertEqual(evaluate(r,dict(f,stress_weekly=-.4,close=12,ema20=11,ema50=10,macd_histogram=1))["status"],"no_signal")
    def test_stale_missing_gaps(self):
        self.assertTrue(all(v is None for v in features(self.refs(),observed_at=T+22201).values()))
        r=self.refs(); r["financial_stress"]["data"]["observations"][0]["date"]="2026-10-30"
        self.assertIsNone(features(r,observed_at=T)["stress_weekly"])
        r=self.refs(); r["market_vix"]["observed_at"]=T+1
        self.assertIsNone(features(r,observed_at=T)["vix_daily"])
        with self.assertRaises(ValueError): parse("observation_date,VIXCLS\n2026-11-20,30\n","market_vix",NOW)
