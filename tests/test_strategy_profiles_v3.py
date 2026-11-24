import unittest,json
from tempfile import TemporaryDirectory
from pathlib import Path
from tradebot.strategy_profiles_v3 import forward_profiles,build,advisory
from tradebot.strategy_validation_v3 import group_profile
def row(start,ret,status="observed"):
    return dict(rule_id="B01",frame="5m",direction="LONG",horizon_minutes=60,event_id=str(start),reference_start=start,reference_end=start+3600,status=status,directional_return_pct=ret,favorable_excursion_pct=1,adverse_excursion_pct=.2,regime={"trend":"range"})
class ProfilesTests(unittest.TestCase):
    def test_forward_overlap_and_cost(self):
        p=forward_profiles([row(100,1),row(200,9),row(3700,-.2),row(7300,None,"pending")])["B01"][0]
        self.assertEqual(p["nonoverlapping_samples"],2)
        self.assertEqual(p["overlap_excluded"],1)
        self.assertEqual(p["pending"],1)
        self.assertAlmostEqual(p["cost_scenarios"]["10"]["mean_pct"],.3)
        self.assertEqual(p["cost_scenarios"]["10"]["positive_fraction"],.5)
        self.assertEqual(p["sample_status"],"insufficient_sample")
        self.assertEqual(p["mean_favorable_excursion_pct"],1)
    def test_profile_and_advisory_scope(self):
        with TemporaryDirectory() as d:
            r=build(d,{"BTCUSD":[row(100,1)],"XAUTUSD":[]},now=10000,coverage_by_market={"BTCUSD":{},"XAUTUSD":{}})
            self.assertEqual(len(r["markets"]["BTCUSD"]["profiles"]),48)
            self.assertEqual(len(r["markets"]["XAUTUSD"]["profiles"]),47)
            s=[dict(id="B01",frame="5m",direction="LONG"),dict(id="G01",frame="5m",direction="LONG")]
            a=advisory(r,"BTCUSD",s,as_of=10000)
            self.assertEqual([x["rule_id"] for x in a["profiles"]],["B01"])
            self.assertFalse(a["execution_authorized"])
            self.assertEqual(advisory(r,"BTCUSD",s,as_of=9999)["status"],"unavailable")
            self.assertEqual(advisory(r,"BTCUSD",s,as_of=10661)["status"],"unavailable")
    def test_group_excursions_and_regime(self):
        x=group_profile([dict(gross_return_pct=.4,exit_reason="time_exit",ambiguous_bar=False,regime={"trend":"range"},favorable_excursion_pct=.8,adverse_excursion_pct=.3)])
        self.assertEqual(x["mean_favorable_excursion_pct"],.8)
        self.assertAlmostEqual(x["regime_profiles"][0]["mean_after_10bps_pct"],.3)
        self.assertEqual(x["sample_status"],"insufficient_sample")
