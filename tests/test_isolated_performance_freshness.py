"""Read-only broker dashboard freshness and local activity tests."""
from contextlib import closing
from datetime import datetime,timedelta,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import sqlite3,time,unittest
from tradebot.isolated_performance import IsolatedPerformanceDashboard,_local_attempt_activity

class FreshnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/"data"
        self.root.mkdir()
        for label,filename in (("btc-isolated","fire-ops.sqlite"),("gold-isolated","fire-xaut.sqlite")):
            child=self.root/label
            child.mkdir()
            with closing(sqlite3.connect(child/filename)) as db:
                db.execute("CREATE TABLE fire_requests(press TEXT,created_at TEXT,status TEXT,result TEXT)")
                for i,status in enumerate(("rejected_no_order","flat_verified","protected_active")):
                    db.execute("INSERT INTO fire_requests VALUES (?,?,?,?)",
                               (f"{i+1:032x}",f"2026-11-23T14:0{i}:00+00:00",status,"{}"))
                db.commit()
        self.dashboard=IsolatedPerformanceDashboard(SimpleNamespace(root=self.root))
        self.dashboard._checked=time.monotonic()

    def test_local_counts_never_claim_trade_pnl(self):
        for label in ("btc-isolated","gold-isolated"):
            a=_local_attempt_activity(self.root/label)
            self.assertEqual(a["status"],"available")
            self.assertEqual((a["recorded_attempts"],a["rejected_attempts"],
                              a["verified_flat_attempts"],
                              a["active_or_unresolved_attempts"]),(3,1,1,1))
            self.assertFalse(a["is_verified_trade_pnl"])

    def test_fresh_and_stale_refresh_state(self):
        now=datetime.now(timezone.utc)
        self.dashboard._report={"checked_at":now.isoformat(),"accounts":{}}
        a=self.dashboard.snapshot()
        self.assertEqual(a["refresh_status"],"fresh")
        self.assertFalse(a["stale"])
        self.assertEqual(a["attempt_activity"]["BTC"]["recorded_attempts"],3)
        self.dashboard._report={"checked_at":(now-timedelta(hours=2)).isoformat(),"accounts":{}}
        a=self.dashboard.snapshot()
        self.assertTrue(a["stale"])
        self.assertEqual(a["refresh_status"],"stale")
        self.dashboard._updating=True
        self.assertEqual(self.dashboard.snapshot()["refresh_status"],"refreshing")

    def test_missing_ledger_not_zero(self):
        missing=self.root/"gold-isolated"/"fire-xaut.sqlite"
        missing.unlink()
        a=self.dashboard.snapshot()["attempt_activity"]["GOLD"]
        self.assertEqual(a["status"],"unavailable")
        self.assertIsNone(a["recorded_attempts"])
        self.assertFalse(missing.exists())

    def test_activity_updates_without_broker_refresh(self):
        self.assertEqual(self.dashboard.snapshot()["attempt_activity"]["BTC"]["recorded_attempts"],3)
        p=self.root/"btc-isolated"/"fire-ops.sqlite"
        with closing(sqlite3.connect(p)) as db:
            db.execute("INSERT INTO fire_requests VALUES(?,?,?,?)",
                       ("f"*32,"2026-11-23T14:10:00+00:00","rejected_no_order","{}"))
            db.commit()
        a=self.dashboard.snapshot()["attempt_activity"]["BTC"]
        self.assertEqual((a["recorded_attempts"],a["rejected_attempts"]),(4,2))

if __name__=="__main__":
    unittest.main()