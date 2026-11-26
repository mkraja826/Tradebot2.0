import unittest
from recover_trading.liquidation_ema9_multiframe import analyze, frozen
from recover_trading.tb2_backtest_tools import simulate, VARIANTS

def sample():
    t=6000; end=t+3600
    minute={i:(100,102,99,101,1) for i in range(t,end,60)}
    em={i//900*900:(100,100,1) for i in range(t,end,60)}
    entry=100.02
    d=dict(id=str(t),opened=t,closed=end,first=t,last=end,sign=1,entry=entry,
           qty=1/entry,rate=15/20000,sl=95,tp=110,target_at_entry=110,actual=None)
    r=dict(version="liquidation-ema9-research-v1",symbol="BTCUSD",status="observed",execution_effect="none",
           start=5900,split=10000,end=15000,assumptions=dict(round_trip_fee_bps=15,entry_slippage_bps=2,hold_minutes=60,ema_variant="15m V8"),
           trades=[dict(entry_at=t,observed_ms=5990000,direction="LONG",liquidation_side="LONG",kind="reversal",partition="development",
                        initial_stop=95,target=110,entry_price=entry,fixed=simulate(d,minute,em,900,None,"original"),
                        adaptive=simulate(d,minute,em,900,VARIANTS["V8"],"original"))])
    return r,minute,em

class MultiFrame(unittest.TestCase):
    def test_matched_coverage_and_v8(self):
        r,m,e=sample()
        out=analyze(r,m,{"15m":e,"1m":{i:(100,100,1) for i in m}})
        self.assertEqual(out["status"],"observed")
        self.assertEqual(len(out["frames"]),6)
        self.assertEqual(out["frames"]["15m"]["groups"]["all_all"]["V8"]["costs"]["2"]["improvement_bps"],0)
        self.assertEqual(out["frames"]["1h"]["eligible"],0)
        self.assertEqual(len(out["common_ids"]),1)

    def test_reproduction_required(self):
        r,m,e=sample()
        r["trades"][0]["fixed"]["net"]["2"]+=1
        self.assertEqual(analyze(r,m,{"15m":e})["status"],"cohort_reproduction_failed")

    def test_reject_invalid_partition(self):
        r,m,e=sample()
        r["trades"][0]["partition"]="holdout"
        with self.assertRaises(ValueError):frozen(r)

if __name__=="__main__":
    unittest.main()
