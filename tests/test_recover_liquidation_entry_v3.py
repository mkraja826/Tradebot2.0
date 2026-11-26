import unittest
from recover_trading.liquidation_entry_v3 import intensity, retest, summarize, analyze, SOURCE, POLICIES

def obs(t,size=2,side="LONG"):
    return dict(source=SOURCE,status="observed_research_only",as_of_ms=t,
        features=dict(interval_s=300,price_move_bps=-25 if side=="LONG" else 25,oi_change_pct=-.2,
        observed_sizes_btc={side:str(size)},observed_counts={side:3}))

def b(o=100,h=101,l=99,c=100):return (o,h,l,c,1)

class EntryV3Tests(unittest.TestCase):
    def test_relative_only_earlier_positive_spaced(self):
        t=10000000
        prior=[(t-i*480000,obs(t-i*480000,1)) for i in range(6,0,-1)]
        x=intensity(t,obs(t,3),"LONG",prior)
        self.assertEqual(x["reference_count"],6)
        self.assertAlmostEqual(x["ratio"],3)
        self.assertTrue(x["qualifies"])
        self.assertEqual(intensity(t,obs(t),"LONG",prior[:4])["status"],"insufficient_reference")

    def test_reversal_and_continuation_retest(self):
        t=6000
        minute={i:b() for i in range(t-300,t,60)}
        minute[t]=b(100,103,99,102)
        minute[t+60]=b(102,103,101,102)
        self.assertEqual(retest("LONG",t*1000,minute,"reversal"),((t+120,1,"reversal"),None))
        self.assertEqual(retest("SHORT",t*1000,minute,"continuation"),((t+120,1,"continuation"),None))
        del minute[t+60]
        self.assertEqual(retest("LONG",t*1000,minute,"reversal")[1],"missing_confirmation_path")

    def test_unknown_not_zero(self):
        rows=[{"policies":{"p":{"status":"unknown","reason":"missing"}}},
              {"policies":{"p":{"status":"no_trade","reason":"no_confirmation"}}}]
        r=summarize(rows,"p")
        self.assertEqual(r["states"],{"unknown":1,"no_trade":1})
        self.assertFalse(r["exits"]["fixed"]["2"]["complete_opportunity_coverage"])
        self.assertEqual(r["exits"]["fixed"]["2"]["known_opportunity_metrics_bps"]["breakeven"],1)

    def test_shared_reservation(self):
        t=6000;start=5900;split=11000;end=17000
        minute={i:b() for i in range(t-300,t+4200,60)}
        minute[t]=b(100,103,99,102)
        minute[t+60]=b(102,103,101,102)
        maps={f:{i//s*s:(100,100,1) for i in minute} for f,s in (("1m",60),("3m",180))}
        out=analyze([(t*1000,obs(t*1000)),((t+300)*1000,obs((t+300)*1000))],minute,maps,start,split,end)
        self.assertEqual(out["opportunities"],1)
        self.assertEqual(out["exclusions"]["shared_reservation"],1)
        self.assertEqual(set(out["events"][0]["policies"]),set(POLICIES))
        self.assertEqual(out["events"][0]["policies"]["intensity_breakout"]["status"],"unknown")
        self.assertEqual(out["events"][0]["policies"]["reversal_retest"]["status"],"simulated_trade")

if __name__=="__main__":unittest.main()
