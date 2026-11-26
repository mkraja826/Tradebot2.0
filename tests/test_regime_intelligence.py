import tempfile
import unittest
from pathlib import Path
from recover_trading.regime_intelligence import build, report, metrics

class RegimeIntelligenceTests(unittest.TestCase):
    def row(self,i,t,ret=20,rule="G01",status="observed",regime="trending",side="LONG"):
        return (i,rule,"5m",side,regime,"normal",t-1,t*1000000,100,900,status,
                (t+900)*1000000,100*(1+ret/10000*(1 if side=="LONG" else -1)),ret)
    def group(self,rows):
        r=build("XAUTUSD",rows,5000,10000)
        return next(g for g in r["groups"] if g["level"]=="rule" and g["id"]=="G01")
    def test_split_purge_overlap_and_holdout(self):
        g=self.group([self.row("a",1000),self.row("b",1100),self.row("c",4500),self.row("d",6000,40),self.row("e",9500)])
        self.assertEqual(g["selection_counts"]["overlap_excluded"],1)
        self.assertEqual(g["selection_counts"]["purged_split_boundary"],1)
        self.assertEqual(g["selection_counts"]["outside_mature_window"],1)
        s=g["strata"][0]
        self.assertEqual(s["development"]["samples"],1)
        self.assertEqual(s["holdout"]["samples"],1)
        self.assertEqual(s["holdout"]["cost_scenarios"][1]["mean_net_bps"],25)
    def test_select_before_outcome_filter(self):
        g=self.group([self.row("a",1000,status="missed"),self.row("b",1100),self.row("c",6000)])
        self.assertEqual(g["selection_counts"]["overlap_excluded"],1)
        self.assertEqual(g["strata"][0]["development"]["samples"],0)
    def test_anomaly_and_mismatch(self):
        a=list(self.row("a",1000));a[-1]=999
        g=self.group([tuple(a),self.row("b",2500,1100),self.row("c",6000)])
        self.assertEqual(g["selection_counts"]["return_mismatch"],1)
        self.assertEqual(g["selection_counts"]["large_return_review"],1)
    def test_currency_market_rule_isolation(self):
        r=build("XAUTUSD",[self.row("a",1000,rule="B01"),self.row("b",6000)],5000,10000)
        self.assertEqual(r["invalid_records"],1)
        self.assertEqual(len(r["groups"]),2)
    def test_empty_and_missing(self):
        self.assertEqual(metrics([])["samples"],0)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"BTCUSD"
            self.assertEqual(report(p,"BTCUSD",100,200)["status"],"unavailable")
            self.assertFalse(p.exists())
