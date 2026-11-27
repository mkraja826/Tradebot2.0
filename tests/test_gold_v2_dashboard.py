import json
import tempfile
import unittest
from pathlib import Path
from recover_trading.gold_v2_dashboard import read_status

NOW=3600020
class GoldDashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def write(self,data):
        (self.root/"gold_v2_status.json").write_text(json.dumps(data))
    def test_missing(self):
        self.assertEqual(read_status(self.root,NOW)["status"],"unavailable")
        self.assertEqual(list(self.root.iterdir()),[])
    def test_stale(self):
        self.write({"symbol":"XAUTUSD","timestamp":NOW-181})
        self.assertEqual(read_status(self.root,NOW)["status"],"stale")
    def test_future(self):
        self.write({"symbol":"XAUTUSD","timestamp":NOW+1})
        self.assertEqual(read_status(self.root,NOW)["status"],"unavailable")
    def test_wrong_symbol(self):
        self.write({"symbol":"BTCUSD","timestamp":NOW})
        self.assertEqual(read_status(self.root,NOW)["status"],"unavailable")
    def test_projection(self):
        self.write({"symbol":"XAUTUSD","timestamp":NOW,"execution_enabled":False,
                    "account":{"position_state":"flat","user_id":"private","balance":100},
                    "technical":{"300":{"ema":[100,99,98,97],"atr":2,"rsi14":50}},
                    "intelligence":{"macro_bias":"mixed_or_flat","macro":{"real_yield_5obs_bp":-4}},
                    "validation":{"observed_nonoverlapping_windows":4,"target_windows":1000},
                    "secret":"private"})
        p=read_status(self.root,NOW)
        self.assertEqual(p["status"],"observed")
        self.assertEqual(p["technical"]["300"]["ema"][0],100)
        self.assertEqual(p["macro"]["real_yield_5obs_bp"],-4)
        self.assertFalse(p["execution_enabled"])
        self.assertNotIn("private",json.dumps(p))
    def test_nonfinite(self):
        self.write({"symbol":"XAUTUSD","timestamp":NOW,"technical":{"300":{"atr":float("nan")}}})
        self.assertIsNone(read_status(self.root,NOW)["technical"]["300"]["atr"])
    def test_malformed_json(self):
        (self.root/"gold_v2_status.json").write_text("{")
        self.assertEqual(read_status(self.root,NOW)["status"],"unavailable")
    def test_comparison_cap(self):
        self.write({"symbol":"XAUTUSD","timestamp":NOW,"validation":{"combined_comparisons":[{"family":"test"}]*201}})
        self.assertEqual(len(read_status(self.root,NOW)["validation"]["combined_comparisons"]),200)
