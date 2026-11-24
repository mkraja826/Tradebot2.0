import unittest
from datetime import datetime,timezone
from tradebot.advanced_indicators_v3 import atr_series,supertrend,pivots,divergence,advanced_technicals,daily_pivots
from tradebot.session_context_v3 import session_features,ticker_changes
from test_indicators_v3 import bars
class AdvancedTests(unittest.TestCase):
    def test_atr_and_supertrend(self):
        for mode,sign in (("up",1),("down",-1)):
            rows=bars(mode=mode); h,l,c=([r[k] for r in rows] for k in ("high","low","close"))
            self.assertEqual(atr_series(h,l,c,14)[-1],2)
            level,direction=supertrend(h,l,c)
            self.assertEqual(direction,sign)
            self.assertEqual(level,c[-1]-sign*6)
        self.assertEqual(supertrend([1],[1],[1]),(None,None))
    def test_confirmed_pivots(self):
        x=[1,2,5,2,1,2,8,2]
        self.assertEqual(pivots(x),[2])
        self.assertEqual(pivots(x+[1]),[2,6])
        self.assertEqual(pivots([1,2,2,2,1]),[])
    def test_divergence(self):
        price=[1,2,4,2,1,3,5,2,1]
        c=[1,2,9,2,1,3,6,2,1]
        self.assertEqual(divergence(c,price,[2,6],True,lambda x:x[-1]),1)
        self.assertIsNone(divergence(c,price,[2],True,lambda x:x[-1]))
    def test_advanced_and_daily(self):
        x=advanced_technicals(bars())
        self.assertEqual(x["atr14_percentile100"],100)
        self.assertIsNone(x["confirmed_swing_high"])
        self.assertIsNone(x["fib_618"])
        self.assertEqual(daily_pivots(dict(high=12,low=8,close=10)),dict(pivot=10,r1=12,s1=8,r2=14,s2=6))
    def test_session_dst_and_missing(self):
        now=int(datetime(2026,7,1,8,0,tzinfo=timezone.utc).timestamp())
        rows=[dict(time=t,open=10,high=11,low=9,close=10,volume=1) for t in range(now-3600,now,300)]
        x=session_features(rows,as_of=now)
        self.assertEqual(x["london_active"],1)
        self.assertEqual(x["london_vwap"],10)
        self.assertIsNone(session_features(rows[1:],as_of=now)["london_vwap"])
    def test_oi_changes_no_future_or_old_anchor(self):
        now=1800000000
        def r(t,oi,f): return dict(timestamp_us=t*1000000,open_interest_raw=oi,funding_rate_raw=f)
        rows=[r(now-300,100,.01),r(now,110,.02),r(now+1,999,8)]
        x=ticker_changes(rows,as_of=now)
        self.assertAlmostEqual(x["oi_change_pct_5m"],10)
        self.assertAlmostEqual(x["funding_raw_change_5m"],.01)
        self.assertIsNone(x["oi_change_pct_15m"])
        self.assertIsNone(ticker_changes(rows,as_of=now+500)["oi_change_pct_5m"])
