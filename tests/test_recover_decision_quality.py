import unittest
from recover_trading.decision_quality import report
class QualityTests(unittest.TestCase):
    def test_failures_not_losses_and_fill_geometry(self):
        r={"status":"observed","outcome_counts":{"decision_failed":3},"recent":[{"id":"a","filled_contracts":"1","entry_deviation_bps":20,"fill_stop_bps":50,"fill_target_bps":-10},{"id":"b","outcome":"submission_unknown"},{"id":"c","filled_contracts":"2","entry_deviation_bps":0,"fill_stop_bps":50,"fill_target_bps":80,"outcome":"closed_reconciled","net_before_funding":"5"}]}
        p={"recover_attributed":{"closed_episodes":1,"losses_before_funding":0,"net_before_funding":"5"}}
        s={"status":"observed","by_decision_position":{"unknown":{"short":2}}}
        m={"status":"observed","actions":{"maintain":4},"autonomous_attempts":[{"status":"verified","count":1}]}
        q=report(r,p,{},s,m);counts={x["finding"]:x["count"] for x in q["findings"]}
        self.assertEqual(q["closed_recover_losses"],0)
        self.assertEqual(q["filled_decision_samples"],2)
        self.assertEqual(counts["provider_or_validation_failures"],3)
        self.assertEqual(counts["planned_bracket_incompatible_with_observed_fill"],1)
        self.assertEqual(counts["verified_autonomous_mutations"],1)
        self.assertEqual(q["invalid_geometry_decision_ids"],["a"])
    def test_missing_reports(self):
        q=report({},{},{},{},{})
        self.assertIsNone(q["closed_recover_episodes"])
        self.assertEqual(q["status"],"review_unavailable")
        self.assertEqual(q["execution_effect"],"none")
