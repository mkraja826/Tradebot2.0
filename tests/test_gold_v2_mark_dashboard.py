import unittest,json
from tempfile import TemporaryDirectory
from pathlib import Path
from recover_trading.gold_v2_dashboard import read_mark_status,read_mark_learning
SOURCE="corroborated_production_mark"
NOW=3600000
class MarkDashboardTests(unittest.TestCase):
    def test_mark_projection_and_source(self):
        with TemporaryDirectory() as d:
            p=Path(d)/"hybrid_status.json"
            x={"symbol":"XAUTUSD","mode":"hybrid_research_only","signal_source":SOURCE,"timestamp":NOW,
               "summary":{"signal_source":SOURCE,"quote_count":7,"actual_fills":99,
                          "management_pairs":[{"family":"fixture","paired_samples":4,"secret":"hidden"}]},
               "latest_signal":{"reference_quality":{"900":{"status":"historical_volatility_corroborated"}}}}
            p.write_text(json.dumps(x))
            r=read_mark_status(d,NOW)
            self.assertEqual(r["status"],"observed")
            self.assertEqual(r["actual_fills"],0)
            self.assertEqual(r["reference_quality"]["900"],"historical_volatility_corroborated")
            self.assertNotIn("secret",r["management_pairs"][0])
            x["signal_source"]="delta_india_production_reference";p.write_text(json.dumps(x))
            self.assertEqual(read_mark_status(d,NOW)["status"],"unavailable")
    def test_learning_snapshot(self):
        with TemporaryDirectory() as d:
            p=Path(d)/"mark_learning_status.json"
            x={"version":"gold-v2-mark-learning.1","signal_source":SOURCE,"automatic_promotion":False,
               "as_of":NOW,"cutoff":NOW-100,"proposals":[{"family":"fixture","train_samples":30,
               "holdout_selected_only":{"30":{"mean_net_bps":12}},"secret":"hidden"}]}
            p.write_text(json.dumps(x))
            r=read_mark_learning(d,NOW)
            self.assertEqual(r["status"],"observed")
            self.assertEqual(r["proposals"][0]["holdout_net_bps_30"],12)
            self.assertNotIn("secret",r["proposals"][0])
            self.assertEqual(read_mark_learning(d,NOW+86401)["status"],"stale")
            self.assertEqual(read_mark_learning(d,NOW-1)["status"],"unavailable")
            x["automatic_promotion"]=True;p.write_text(json.dumps(x))
            self.assertEqual(read_mark_learning(d,NOW)["status"],"unavailable")
