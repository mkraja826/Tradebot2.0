import unittest
from recover_trading.calibration import candidate_report,DAY
class CalibrationTests(unittest.TestCase):
    def test_training_only(self):
        start=1800000000
        split=start+63*DAY
        events=[{"rule_id":"B01","horizon_s":3600,"partition":"development","decision_at":start+w*7*DAY+d*DAY,"exit_at":start+w*7*DAY+d*DAY+3900,"net_bps":10} for w in range(9) for d in range(6)]
        report={"symbol":"BTCUSD","start":start,"split":split,"complete":True,"cost_bps_round_trip":15,"events":events}
        a=candidate_report(report,draws=100)
        self.assertEqual(a["positive_training_candidates"],1)
        report["events"]=events+[{"partition":"holdout","rule_id":"B01","net_bps":-9999}]
        self.assertEqual(a,candidate_report(report,draws=100))
        self.assertFalse(a["execution_weights_changed"])
    def test_reject_cross_boundary(self):
        r={"complete":True,"start":1,"split":10000,"events":[{"partition":"development","rule_id":"B01","decision_at":5000,"exit_at":10000}]}
        with self.assertRaises(ValueError):candidate_report(r)
