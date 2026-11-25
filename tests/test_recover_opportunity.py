import unittest
from recover_trading.opportunity import opportunity
from recover_trading.excursions import excursion
class OpportunityTests(unittest.TestCase):
    def test_levels_and_stale_quotes(self):
        t=1800000000
        report={"as_of":t,"market_context":{"quotes":{"ticker":{"timestamp_us":t*1000000,"mark":100,"bid":99.9,"ask":100.1}},
          "frames":{"15m":{"status":"ready","closed_at":t,"features":{"atr14":2,"prior_high20":105,"prior_low20":96}},
                    "5m":{"status":"ready","closed_at":t-600,"features":{"prior_high20":101}}},
          "context":{"previous_day_high":110}}}
        x=opportunity(report,{"direction":"LONG"})
        self.assertEqual(x["directional_level"]["price"],105)
        self.assertEqual(x["opposing_level"]["price"],96)
        self.assertAlmostEqual(x["observed_spread_bps"],20)
        self.assertEqual(x["atr_by_frame"]["15m"]["cost_fraction_of_atr"],.075)
        self.assertEqual(opportunity(report,{"direction":"SHORT"})["directional_level"]["price"],96)
        report["as_of"]+=121
        self.assertEqual(opportunity(report,{"direction":"LONG"})["status"],"quote_unavailable")
    def test_excursion_excludes_exit_high_and_handles_short(self):
        t=1800000000
        bars={t:{"time":t,"open":100,"high":104,"low":97,"close":101,"volume":1},
              t+300:{"time":t+300,"open":101,"high":999,"low":1,"close":101,"volume":1}}
        e={"entry_at":t,"exit_at":t+300,"entry":100,"exit":101,"side":"LONG"}
        x=excursion(bars,e)
        self.assertAlmostEqual(x["mfe_bps"],400)
        self.assertAlmostEqual(x["mae_bps"],300)
        e["side"]="SHORT"
        x=excursion(bars,e)
        self.assertAlmostEqual(x["mfe_bps"],300)
        self.assertAlmostEqual(x["mae_bps"],400)
        e["entry"]=999
        self.assertIsNone(excursion(bars,e))
