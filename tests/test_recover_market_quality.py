import unittest,tempfile
from pathlib import Path
from unittest.mock import patch
from recover_trading.market_quality import diagnostics
from recover_trading import forward_validation
class QualityTests(unittest.TestCase):
    def test_scan_cutoff_distinct_from_observation(self):
        t=1800000000
        r={"symbol":"BTCUSD","as_of":t+310,"candle_as_of":t+299,
           "feed_health":{"candle:5m":{"status":"ready"}},
           "market_context":{"frames":{"5m":{"status":"ready","closed_at":t}},
                            "quotes":{"ticker":{"timestamp_us":(t+309)*1000000}}}}
        with tempfile.TemporaryDirectory() as d:
            q=diagnostics(r,Path(d)/"absent.sqlite")
        self.assertEqual(q["frames"]["5m"]["lag_at_scan_s"],0)
        self.assertEqual(q["frames"]["5m"]["lag_at_observation_s"],300)
        self.assertEqual(q["quotes"]["ticker"]["age_s"],1)
        self.assertIsNone(q["recent_24h"])
        self.assertEqual(q["execution_effect"],"none")
    def test_timer_exit_reports_failure(self):
        with patch("sys.argv",["forward","--data-dir","unused"]),patch.object(forward_validation,"run",side_effect=[ValueError(),{"symbol":"XAUTUSD"}]) as run:
            self.assertEqual(forward_validation.main(),1)
            self.assertEqual(run.call_count,2)
