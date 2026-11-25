import tempfile
import unittest
from pathlib import Path
import sqlite3
from recover_trading.direction import direction_for, REGISTRY
from recover_trading.regime import FAMILIES, market_regime, weighted_votes
from recover_trading.research import SignalResearch
from test_recover_decision import report
from test_recover_direction import sig

class AdaptiveTests(unittest.TestCase):
    def test_registry_mapping(self):
        ids={r.id for rules,_ in REGISTRY.values() for r in rules}|{k for _,ds in REGISTRY.values() for k in ds}
        self.assertEqual(set(FAMILIES),ids)
    def test_regime(self):
        def frame(a,b,adx): return {"status":"ready","features":{"ema50":a,"ema200":b,"adx14":adx}}
        market={"frames":{"1h":frame(90,100,30),"4h":frame(80,100,26),
                          "5m":{"status":"ready","features":{"atr14_percentile100":90}}}}
        x=market_regime(market)
        self.assertEqual((x["regime"],x["trend_bias"],x["volatility"]),("trending","SHORT","high"))
        market["frames"]["1h"]=frame(90,100,15)
        market["frames"]["4h"]=frame(80,100,16)
        self.assertEqual(market_regime(market)["regime"],"ranging")
        self.assertEqual(market_regime({})["regime"],"unknown")
    def test_family_saturation(self):
        regime=market_regime({})
        groups={"LONG":[{"id":k} for k in ("B01","B02","B04","B05","B25")],"SHORT":[{"id":"B03"},{"id":"B14"}]}
        scores,_=weighted_votes(groups,regime)
        self.assertEqual(scores,{"LONG":15000,"SHORT":20000})
    def test_research_duplicate_and_forward_return(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"samples.sqlite"
            r=report(); stamp=r["as_of"]
            r["market_context"]["quotes"]["ticker"]={"timestamp_us":stamp*1000000,"mark":100}
            x=direction_for(r)
            j=SignalResearch(path)
            self.assertEqual(j.record(r,x)["new_horizon_samples"],3)
            self.assertEqual(j.record(r,x)["new_horizon_samples"],0)
            r["signals"]=[]; r["as_of"]=stamp+900
            r["market_context"]["quotes"]["ticker"]={"timestamp_us":r["as_of"]*1000000,"mark":99}
            self.assertEqual(j.record(r,direction_for(r))["observed"],1)
            with sqlite3.connect(path) as db:
                rows=db.execute("SELECT status,return_bps FROM observations WHERE horizon_s=900").fetchone()
            self.assertEqual(rows[0],"observed")
            self.assertAlmostEqual(rows[1],100)
            r["as_of"]=stamp+4000
            r["market_context"]["quotes"]["ticker"]["timestamp_us"]=r["as_of"]*1000000
            self.assertEqual(j.record(r,direction_for(r))["missed"],1)
