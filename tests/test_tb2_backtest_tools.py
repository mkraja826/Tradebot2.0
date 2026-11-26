import json,sqlite3,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from recover_trading.tb2_backtest_tools import (indicators,simulate,compare,prepare,register_backtests,run)

class FakeMCP:
    def __init__(self):self.tools={}
    def tool(self):
        def add(f):self.tools[f.__name__]=f;return f
        return add

class BacktestTests(unittest.TestCase):
    def trade(self,sign=1):
        return dict(id="a"*64,opened="2026-01-01T00:00:00Z",closed="2026-01-01T00:03:00Z",
                    sign=sign,entry=100,qty=1,rate=.0005,actual=0,first=0,last=180,
                    sl=95 if sign==1 else 105,tp=120 if sign==1 else 80,target_at_entry=120 if sign==1 else 80)
    def test_confirmed_warmup_and_reset(self):
        bs={60*i:(100,102,99,101,None) for i in range(105)}
        em=indicators(bs,60)
        self.assertEqual(list(em),[6300])
        self.assertNotIn(6240,em)
        bs[6420]=(100,102,99,101,None)
        self.assertNotIn(6480,indicators(bs,60))
    def test_long_stop_never_widens(self):
        t=self.trade();bars={0:(100,103,99,102),60:(104,105,102,104),120:(104,105,100,101)}
        em={0:(98,115,2),60:(101,115,2),120:(99,115,2)}
        r=simulate(t,bars,em,60,(0,False),"original")
        self.assertEqual(r["final_sl"],101);self.assertEqual(r["exit_price"],101)
    def test_short_stop_never_widens(self):
        t=self.trade(-1);bars={0:(100,101,97,98),60:(96,98,95,96),120:(96,100,95,99)}
        em={0:(102,85,2),60:(99,85,2),120:(101,85,2)}
        r=simulate(t,bars,em,60,(0,False),"original")
        self.assertEqual(r["final_sl"],99);self.assertEqual(r["exit_price"],99)
    def test_gap_precedes_amendment(self):
        t=self.trade();r=simulate(t,{0:(94,100,90,99)},{0:(99,115,2)},60,(0,False),"original")
        self.assertEqual((r["reason"],r["exit_price"]),("stop_gap",94))
    def test_dual_touch_stop_first(self):
        r=simulate(self.trade(),{0:(100,121,94,110)},{0:(99,115,2)},60,None,"original")
        self.assertTrue(r["dual_touch"]);self.assertEqual(r["exit_price"],95)
    def test_delayed_and_fee_slippage(self):
        t=self.trade();bars={0:(100,102,99,102),60:(103,104,102,103),120:(103,104,99,100)}
        em={0:(99,115,2),60:(101,115,2),120:(100,115,2)}
        r=simulate(t,bars,em,60,(.5,True),"original")
        self.assertTrue(r["activated"]);self.assertEqual(r["final_sl"],100)
        self.assertGreater(r["net"]["0"],r["net"]["5"])
    def test_fixed_and_dynamic_target(self):
        t=self.trade();t["target_at_entry"]=105
        bars={0:(100,104,99,103),60:(103,106,102,104),120:(104,106,103,105)}
        em={0:(98,105,2),60:(98,102,2),120:(98,102,2)}
        self.assertEqual(simulate(t,bars,em,60,(0,False),"fixed_ema21")["exit_price"],105)
        self.assertEqual(simulate(t,bars,em,60,(0,False),"dynamic_ema21")["reason"],"ema_target_crossed_at_update")
    def test_matched_comparison(self):
        r=simulate(self.trade(),{0:(100,121,94,110)},{0:(99,115,2)},60,None,"original")
        x=compare([r],{r["id"]:r})
        self.assertEqual(x["delta_vs_fixed_bracket"]["2"]["unchanged"],1)
    def test_registration_and_read_only_candles(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);m=FakeMCP();register_backtests(m,data_dir=p,learning_dir=p/"learning")
            self.assertEqual(set(m.tools),{"historical_candles","ema_backtest","trade_replay","backtest_comparison"})
            with self.assertRaises(ValueError):m.tools["historical_candles"]("../other","1m",0,60)
            with self.assertRaises(ValueError):m.tools["historical_candles"]("BTCUSD","1m",0,60,501)
            self.assertEqual(m.tools["ema_backtest"]("BTCUSD","1m",0,60)["execution_effect"],"none")
            self.assertFalse((p/"BTCUSD").exists())
            root=p/"BTCUSD";root.mkdir();db=root/"market.sqlite"
            with sqlite3.connect(db) as c:
                c.execute("CREATE TABLE samples(symbol,series,stamp INTEGER,payload)")
                for t in (0,60,120):
                    c.execute("INSERT INTO samples VALUES(?,?,?,?)",("BTCUSD","candle:1m",t,json.dumps(dict(time=t,open=100,high=102,low=99,close=101,volume=2))))
            before=db.read_bytes()
            r=m.tools["historical_candles"]("BTCUSD","1m",0,150,1)
            self.assertEqual((r["available"],r["next_offset"]),(2,1))
            self.assertEqual(db.read_bytes(),before)
    def test_cohort_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            for f in ("market.sqlite","orders.sqlite","decisions.sqlite","learning.sqlite"):(p/f).touch()
            with patch("recover_trading.trade_intelligence.report",return_value={"trades":[],"coverage":{}}):
                r=run(p,p,"BTCUSD",0,60,["1m"],"original",26)
            self.assertEqual(r["status"],"cohort_count_mismatch")
