import unittest,json,tempfile
from pathlib import Path
from tradebot.dashboard_analytics_v3 import analytics
class AnalyticsTests(unittest.TestCase):
 def test_projection(self):
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp);r=dict(mode="paper_learning_diagnostic_only",checked_at=100,execution_authorized=False,orders_submitted=0,markets={"BTCUSD":{"WAIT":3,"secret":"not projected"}},signal_path_summary=[dict(symbol="BTCUSD",observed=1,raw="not projected")])
        (p/"m21-paper-learning-v3.json").write_text(json.dumps(r))
        a=analytics(p,101)["paper"];self.assertEqual(a["state"],"fresh");self.assertEqual(a["markets"]["BTCUSD"],{"WAIT":3});self.assertEqual(a["groups"],[{"symbol":"BTCUSD","observed":1}])
        self.assertEqual(analytics(p,1000)["paper"]["state"],"historical")
        self.assertEqual(analytics(p,99)["paper"]["state"],"unavailable")
 def test_wrong_mode(self):
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp);(p/"m21-paper-learning-v3.json").write_text('{"mode":"live"}')
        self.assertEqual(analytics(p,100)["paper"]["state"],"unavailable")
