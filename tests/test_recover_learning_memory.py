import unittest
from recover_trading.learning_memory import build
class MemoryTests(unittest.TestCase):
    def test_observations_not_validated_lessons(self):
        l={"status":"observed","lessons":[{"symbol":"BTCUSD","decision_id":"a","closed":"c","net_before_funding":"5"}]}
        q={"status":"observed","findings":[{"finding":"provider_or_validation_failures","count":11},{"finding":"verified_autonomous_mutations","count":1}]}
        r=build("BTCUSD",l,q)
        self.assertEqual(len(r["verified_observations"]),2)
        self.assertEqual(r["process_observations"][0]["evidence_grade"],"repeated_process_observation")
        self.assertEqual(r["statistically_supported_lessons"],[])
        self.assertFalse(r["model_feedback_enabled"])
    def test_prospective_overlap_and_retrospective_excluded(self):
        lessons=[{"symbol":"BTCUSD","decision_id":str(i),"closed":"c","net_before_funding":"1"} for i in range(5)]
        def row(i,a,timing,status,value):
            return {"decision_id":str(i),"closed":"c","start":a,"finish":a+900,"horizon_s":900,"timing":timing,"status":status,"evidence":{"gross_directional_price_return_bps":value}}
        follow=[row(0,0,"prospective_window","missing_candles",None),row(1,300,"prospective_window","observed",100),row(2,900,"prospective_window","observed",-10),row(3,1800,"retrospective_window","observed",999),row(4,2700,"partly_elapsed_at_enrollment","observed",999)]
        r=build("BTCUSD",{"status":"observed","lessons":lessons,"followups":follow},{"status":"observed"})["hypotheses"][0]
        self.assertEqual(r["prospective_nonoverlap_samples"],1)
        self.assertEqual(r["mean_gross_directional_bps"],-10)
        self.assertEqual(r["counts"]["overlap_excluded"],1)
    def test_missing_sources(self):
        r=build("XAUTUSD",{},{})
        self.assertEqual(r["status"],"incomplete_sources")
        self.assertEqual(r["statistical_status"],"not_validated")
