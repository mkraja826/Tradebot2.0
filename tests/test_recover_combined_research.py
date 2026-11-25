import unittest
from recover_trading.combined_research import simulate,metrics,EXITS
from recover_trading.entry_research import simulate as entry
from recover_trading.trailing_research import simulate as trailing
class CombinedTests(unittest.TestCase):
    def setUp(self):
        self.ev={"atr":1,"close":100,"prior_high":104,"prior_low":98}
        self.rows=[{"open":100,"high":101.5,"low":99,"close":101},
                   {"open":101,"high":102,"low":100.5,"close":101.5},
                   {"open":101.5,"high":102,"low":101,"close":101.6},
                   {"open":101.6,"high":999,"low":1,"close":1}]
    def test_time_exit_matches_entry_module(self):
        for en in ("original","delay_5m","delay_10m","confirm_direction","pullback_reclaim"):
            for side in ("LONG","SHORT"):
                a=simulate(self.rows,side,self.ev,en,"time_exit",15)
                b=entry(self.rows,side,en,15)
                for k in b:self.assertEqual(a[k],b[k])
    def test_delayed_bracket_ignores_pre_entry_extremes(self):
        rows=[dict(self.rows[0],high=999,low=1),*self.rows[1:]]
        a=simulate(rows,"LONG",self.ev,"delay_5m","trail_1atr",15)
        b=trailing(rows[1:],"LONG",100,15,"trail_1atr")
        self.assertAlmostEqual(a["net_bps"],b["net_bps"])
        self.assertEqual(a["delay_s"],300)
    def test_all_models_and_untriggered(self):
        for ex in EXITS:
            r=simulate(self.rows,"LONG",self.ev,"pullback_reclaim",ex,15)
            self.assertFalse(r["entered"])
            self.assertEqual(r["net_bps"],0)
        a=simulate(self.rows,"LONG",self.ev,"original","time_exit",15)
        b=simulate(self.rows,"LONG",self.ev,"pullback_reclaim","time_exit",15)
        x=metrics([a,b])
        self.assertEqual(x["entries"],1)
        self.assertAlmostEqual(x["mean_net_bps_per_opportunity"],a["net_bps"]/2)
        self.assertAlmostEqual(x["mean_net_bps_per_entry"],a["net_bps"])
