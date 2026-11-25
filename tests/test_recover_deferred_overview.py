import tempfile,unittest
from pathlib import Path
from recover_trading.deferred_overview import report
class DeferredOverviewTests(unittest.TestCase):
    def test_missing_sources_do_not_create_files(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/"demo"
            b=report(p,"BTCUSD",1795602000);g=report(p,"XAUTUSD",1795602000)
            self.assertEqual([r["id"] for r in b["rules"]],["B17","B18"])
            self.assertEqual([r["id"] for r in g["rules"]],["G20","G21","G25"])
            self.assertTrue(all(not r["execution_enabled"] for r in b["rules"]+g["rules"]))
            self.assertEqual(list(Path(t).iterdir()),[])
