import unittest
from datetime import datetime,timezone
from recover_trading.macro_feed import alfred_csv,ALFRED_SOURCE
from tradebot.gold_macro_v3 import history,features
from tradebot.gold_stress_v3 import parse,features as stress_features
class AlfredTests(unittest.TestCase):
    def test_exact_vintage_and_aligned_yields(self):
        t=datetime(2026,11,25,10,tzinfo=timezone.utc)
        def read(url):
            ident=url.split("id=")[1].split("&")[0]
            return "observation_date,"+ident+"_20261125\n"+"\n".join("2026-11-"+str(d)+","+str(v) for d,v in zip((16,17,18,19,20,23,25),(4,4,4,4,4,3.9,999)))
        raw=alfred_csv("yields",t,read);h=history(raw,"yields",t)
        r=features({"yields":{"status":"ready","observed_at":t.timestamp(),"macro_history":{"source":ALFRED_SOURCE,"series":h}}},observed_at=t.timestamp())
        self.assertAlmostEqual(r["nominal_yield_5obs_bp"],-10)
        self.assertAlmostEqual(r["real_yield_5obs_bp"],-10)
        with self.assertRaises(ValueError):alfred_csv("broad_dollar",t,lambda url:"observation_date,DTWEXBGS_20261124\n2026-11-20,120")
    def test_stress_source(self):
        t=datetime(2026,11,25,10,tzinfo=timezone.utc)
        data=parse("observation_date,STLFSI4\n2026-11-06,-0.49\n2026-11-13,-0.86\n","financial_stress",t)
        data["source"]=ALFRED_SOURCE
        r=stress_features({"financial_stress":{"status":"ready","observed_at":t.timestamp(),"data":data}},observed_at=t.timestamp())
        self.assertEqual(r["stress_weekly"],-0.86)
