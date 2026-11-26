import unittest
from recover_trading.liquidation_ema9 import burst_side, confirm, prepare_entry, analyze, SOURCE

def evidence(ms, side="LONG"):
    return dict(source=SOURCE, status="observed_research_only", as_of_ms=ms,
                features=dict(price_move_bps=-25 if side=="LONG" else 25, oi_change_pct=-.2,
                              observed_sizes_btc={side:"2"}, observed_counts={side:3}))

def bar(o=100, h=101, l=99, c=100):
    return (o,h,l,c,1)

class LiquidationEMA9Test(unittest.TestCase):
    def test_missing_stale_and_wrong_source(self):
        self.assertIsNone(burst_side(300000,evidence(0)))
        p=evidence(300000);p["source"]="unverified"
        self.assertIsNone(burst_side(300000,p))
        self.assertEqual(burst_side(300000,evidence(300000)),"LONG")
        self.assertEqual(burst_side(300000,evidence(300000,"SHORT")),"SHORT")

    def test_confirmation_after_receipt_and_next_open(self):
        bars={240:bar(),300:bar(100,103,99,102),360:bar(100,103,99,102)}
        self.assertEqual(confirm("LONG",300001,bars),(420,1,"reversal"))
        self.assertEqual(confirm("SHORT",300001,bars),(420,1,"continuation"))
        self.assertIsNone(confirm("LONG",300001,{240:bar(),300:bars[300]}))

    def test_no_wick_confirmation(self):
        bars={240:bar(),**{t:bar(100,110,90,100) for t in range(300,600,60)}}
        self.assertIsNone(confirm("LONG",300000,bars))

    def test_bracket_and_boundary(self):
        t=6000;bars={i:bar() for i in range(t-300,t+3600,60)}
        e1={t:(100,100,2)};e15={i//900*900:(100,100,2) for i in range(t,t+3600,60)}
        x,why=prepare_entry(t,1,bars,e1,e15,t+3600)
        self.assertIsNone(why);self.assertLess(x["sl"],x["entry"]);self.assertGreater(x["tp"],x["entry"])
        self.assertEqual(prepare_entry(t,1,bars,e1,e15,t+3599)[1],"incomplete_horizon")
        x,why=prepare_entry(t,-1,bars,e1,e15,t+3600)
        self.assertIsNone(why);self.assertGreater(x["sl"],x["entry"]);self.assertLess(x["tp"],x["entry"])

    def test_matched_replay_dedup_and_monotonic_stop(self):
        stamp=6000000;entry=6060
        bars={i:bar() for i in range(5700,entry+3600,60)}
        bars[6000]=bar(100,103,99,102)
        e1={entry:(100,100,2)}
        e15={i//900*900:(101,100,1) for i in range(entry,entry+3600,60)}
        out=analyze([(stamp,evidence(stamp)),(stamp+60000,evidence(stamp+60000))],
                    bars,e1,e15,5900,10000,15000)
        self.assertEqual(len(out["trades"]),1)
        self.assertEqual(out["exclusions"]["burst_overlap"],1)
        r=out["trades"][0]
        self.assertGreaterEqual(r["adaptive"]["final_sl"],r["initial_stop"])
        self.assertEqual(r["fixed"]["id"],r["adaptive"]["id"])
        self.assertEqual(out["execution_effect"],"none")

if __name__=="__main__":
    unittest.main()
