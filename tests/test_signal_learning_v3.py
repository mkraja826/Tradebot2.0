import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from tradebot.signal_learning_v3 import evaluate_event,aggregate
from tradebot.learning_engine_v3 import tick
from tradebot.opportunity_journal_v3 import OpportunityJournal
from tradebot.market_store_v3 import MarketStore
from test_opportunity_scanner_v3 import scan,ctx,sig,NOW

def event(j,s="BTCUSD",side="LONG"):
    c=ctx(s); c["context_observed_at"]=NOW+20
    return j.record(scan(s,[sig("B01" if s=="BTCUSD" else "G01",direction=side)]),c)
def candles():
    return [dict(time=NOW+300*(i+1),open=100,high=103,low=99,close=102,volume=1) for i in range(48)]

class LearningTests(unittest.TestCase):
    def test_forward_only_and_pending(self):
        with TemporaryDirectory() as d:
            j=OpportunityJournal(Path(d)/"j.sqlite"); e=event(j)
            calls=[]
            def bars(s,a,b):
                calls.append((s,a,b)); return [r for r in candles() if a<=r["time"]<b]
            r=evaluate_event(e,bars,now=NOW+1200)
            self.assertEqual([x["status"] for x in r],["observed","pending","pending"])
            self.assertEqual(calls,[("BTCUSD",NOW+300,NOW+1200)])
            self.assertAlmostEqual(r[0]["directional_return_pct"],2)
            self.assertAlmostEqual(r[0]["favorable_excursion_pct"],3)
            self.assertAlmostEqual(r[0]["adverse_excursion_pct"],1)
    def test_short_and_missing(self):
        with TemporaryDirectory() as d:
            j=OpportunityJournal(Path(d)/"j.sqlite"); e=event(j,"XAUTUSD","SHORT")
            r=evaluate_event(e,lambda s,a,b:candles()[:3],now=NOW+15000)
            self.assertEqual([x["status"] for x in r],["observed","missing_candles","missing_candles"])
            self.assertAlmostEqual(r[0]["directional_return_pct"],-2)
            self.assertEqual(aggregate(r)[0]["positive_direction_fraction"],0)
    def test_report_isolation(self):
        with TemporaryDirectory() as d:
            p=Path(d); j=OpportunityJournal(p/"opportunities-v3.sqlite"); event(j); event(j,"XAUTUSD","SHORT")
            m=MarketStore(p/"market-v3.sqlite"); m.candles("BTCUSD","5m",candles(),as_of=NOW+14700)
            marker=p/"scanner-status.json"; marker.write_text("unchanged")
            r=tick(p,now=NOW+15000)
            self.assertEqual(r["markets"]["BTCUSD"]["observed"],3)
            self.assertEqual(r["markets"]["XAUTUSD"]["missing"],3)
            self.assertIsNone(r["markets"]["BTCUSD"]["verified_trade_outcomes"])
            self.assertFalse(r["scanner_control"])
            self.assertEqual(marker.read_text(),"unchanged")
