"""Safe quote-drift evidence for blocked BTC plans; never authorize entries."""
from copy import deepcopy
import unittest
from tradebot.fire_execution import _pretrade_quote_distance_evidence


class QuoteDistanceEvidenceTests(unittest.TestCase):
    def test_long_rejected_after_fresh_quote_moves(self):
        plan={"direction":"LONG","stop_loss":"95","take_profit":"106"}
        model={"best_ask":"100"}
        broker={"best_ask":"102"}
        before=deepcopy((plan,model,broker))
        out=_pretrade_quote_distance_evidence(model,broker,plan)
        self.assertTrue(out["model"]["gross_1_to_1_satisfied"])
        self.assertFalse(out["broker"]["gross_1_to_1_satisfied"])
        self.assertEqual(out["model"]["gross_reward_risk"],"1.2")
        self.assertEqual(out["broker"]["gross_reward_risk"],
                         str(4/7) if False else "0.5714285714285714285714285714")
        self.assertEqual((plan,model,broker),before)
        self.assertEqual(out["source"],"snapshot_vs_signed_broker_quote")

    def test_short_rejected_after_fresh_quote_moves(self):
        out=_pretrade_quote_distance_evidence(
            {"best_bid":"100"},{"best_bid":"98"},
            {"direction":"SHORT","stop_loss":"105","take_profit":"94"})
        self.assertTrue(out["model"]["gross_1_to_1_satisfied"])
        self.assertFalse(out["broker"]["gross_1_to_1_satisfied"])

    def test_instantaneously_valid_keeps_equal_geometry(self):
        out=_pretrade_quote_distance_evidence(
            {"best_bid":"100"},{"best_bid":"100"},
            {"direction":"SHORT","stop_loss":"105","take_profit":"95"})
        self.assertTrue(out["broker"]["gross_1_to_1_satisfied"])
        self.assertEqual(out["quote_change_bps"],"0")

    def test_missing_or_untrusted_values_fail_closed(self):
        for plan,model,broker in (
            ({}, {}, {}),
            ({"direction":"WAIT"}, {"best_ask":"100"}, {"best_ask":"100"}),
            ({"direction":"LONG","stop_loss":"99","take_profit":"101"},
             {"best_ask":"NaN"},{"best_ask":"100"}),
            ({"direction":"LONG","stop_loss":"99","take_profit":"101"},
             {"best_ask":"100"},{"best_ask":None}),
        ):
            self.assertEqual(
                _pretrade_quote_distance_evidence(model,broker,plan),{})


if __name__=="__main__":
    unittest.main()