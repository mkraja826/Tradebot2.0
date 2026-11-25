import unittest
from recover_trading.trade_excursion import measure
class ExcursionTests(unittest.TestCase):
    def fixture(self,side):
        ep={"opened":"2026-11-25T00:00:30Z","closed":"2026-11-25T00:03:30Z","direction":"LONG" if side==1 else "SHORT","fills":2}
        f=[{"created_at":ep["opened"],"side":"buy" if side==1 else "sell","size":2,"price":100,"new_position":{"size":side*2}},{"created_at":ep["closed"],"side":"sell" if side==1 else "buy","size":2,"price":101,"new_position":{"size":0}}]
        from recover_trading.performance import stamp
        t=int(stamp(f[0]).timestamp())//60*60
        bars={t+i*60:{"time":t+i*60,"open":100,"close":101,"low":l,"high":h} for i,l,h in ((0,1,999),(1,98,104),(2,97,106),(3,1,999))}
        return ep,f,bars
    def test_long_and_short_boundary_exclusion(self):
        for sign in (1,-1):
            ep,f,b=self.fixture(sign);r=measure(ep,f,b,60)
            self.assertEqual(r["status"],"complete_interior_lower_bound")
            self.assertEqual(r["observed_interior_bars"],2)
            self.assertEqual(r["mfe_bps"],600 if sign==1 else 300)
            self.assertEqual(r["mae_bps"],300 if sign==1 else 600)
    def test_missing_and_multi_entry(self):
        ep,f,b=self.fixture(1)
        self.assertEqual(measure(ep,f,{},60)["status"],"fills_only_lower_bound")
        del b[sorted(b)[1]]
        self.assertEqual(measure(ep,f,b,60)["status"],"partial_coverage_lower_bound")
        ep["fills"]=3
        f.insert(1,{"created_at":"2026-11-25T00:01:30Z","side":"buy","size":1,"price":100,"new_position":{"size":3}})
        self.assertEqual(measure(ep,f,b,60)["status"],"multi_entry_or_reversal_not_supported")
