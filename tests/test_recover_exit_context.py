import unittest
from recover_trading.exit_context import geometry
from recover_trading.management_shadow import context_for,SYSTEM
from test_recover_management_shadow import fixture
class ExitContextTests(unittest.TestCase):
    def test_short_and_long_geometry(self):
        for q,mark,sl,tp in [(-5,"98","99","95"),(5,"102","101","105")]:
            p={"size":q,"entry_price":"100","mark_price":mark,"bracket_state":"matching_legs_observed","legs":[{"type":"stop_loss_order","trigger":sl},{"type":"take_profit_order","trigger":tp}]}
            r=geometry(p,{"mfe_bps":300,"mae_bps":50,"coverage":1},direction="SHORT")
            self.assertAlmostEqual(r["current_gross_mark_return_bps"],200)
            self.assertAlmostEqual(r["stop_trigger_gross_entry_return_bps"],100)
            self.assertAlmostEqual(r["target_trigger_gross_entry_return_bps"],500)
            self.assertAlmostEqual(r["remaining_target_to_stop_distance_ratio"],3)
            self.assertAlmostEqual(r["observed_excursion"]["observed_trade_peak_minus_current_mark_bps"],100)
            self.assertEqual(r["execution_effect"],"none")
    def test_missing_or_crossed(self):
        p={"size":-1,"entry_price":"100","mark_price":"102","bracket_state":"matching_legs_observed","legs":[{"type":"stop_loss_order","trigger":"101"},{"type":"take_profit_order","trigger":"95"}]}
        r=geometry(p)
        self.assertEqual(r["trigger_geometry"],"crossed_or_at_mark")
        self.assertIsNone(r["remaining_target_to_stop_distance_ratio"])
        self.assertNotIn("observed_excursion",r)
        self.assertEqual(geometry({})["status"],"unavailable")
    def test_context_and_prompt(self):
        r,s,p=fixture();c=context_for(r,s,p,1001)
        self.assertIn("exit_geometry",c)
        self.assertEqual(c["exit_geometry"]["current_gross_mark_return_bps"],-100)
        self.assertIn("single-leg amendments",SYSTEM)
