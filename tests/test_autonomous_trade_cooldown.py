"""Independent isolated BTC / Gold broker-verified close cooldown tests.

Fake FIRE histories only; no API keys, no model calls and no broker orders.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sqlite3
import unittest

from tradebot.autonomous_cooldown import post_close_cooldown, COOLDOWN_SECONDS
from tradebot.btc_autonomous_demo import run_once as btc_run
from tradebot.gold_autonomous_demo import run_once as gold_run

T = datetime(2026,11,23,17,0,tzinfo=timezone.utc)


def write_db(root, filename, rows):
    with sqlite3.connect(root/filename) as db:
        db.execute("CREATE TABLE fire_requests (press TEXT, created_at TEXT,"
                   "updated_at TEXT, status TEXT, result TEXT)")
        for i, (created,updated,status,result) in enumerate(rows):
            db.execute("INSERT INTO fire_requests VALUES (?,?,?,?,?)",
                       (str(i), created.isoformat(), updated.isoformat(),
                        status, json.dumps(result)))
        db.commit()


class CooldownTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.btc=self.base/"btc-isolated"
        self.gold=self.base/"gold-isolated"
        for root in (self.btc,self.gold):root.mkdir()

    @staticmethod
    def closed(submitted=True):
        return {"orders_submitted":submitted,
                "broker_order_id":"signed-demo-order-11",
                "reason_code":"verified_no_position_or_orders",
                "protection_verified":False}

    def pair(self,root):
        return "fire-ops.sqlite" if root.name=="btc-isolated" else "fire-xaut.sqlite"

    def test_no_prior_close_means_ready(self):
        for root in (self.btc,self.gold):
            with self.subTest(root=root):
                write_db(root,self.pair(root),[])
                self.assertEqual(post_close_cooldown(
                    root, fire_filename=self.pair(root),now=T),("ready",0))

    def test_trade_close_starts_five_minute_cooldown_not_entry_time(self):
        for root in (self.btc,self.gold):
            with self.subTest(root=root):
                write_db(root,self.pair(root),[
                    (T-timedelta(hours=2),T,self._status(),self.closed())])
                self.assertEqual(post_close_cooldown(
                    root,fire_filename=self.pair(root),now=T),
                    ("cooling_down",COOLDOWN_SECONDS))
                self.assertEqual(post_close_cooldown(
                    root,fire_filename=self.pair(root),
                    now=T+timedelta(minutes=4,seconds=59)),
                    ("cooling_down",1))
                self.assertEqual(post_close_cooldown(
                    root,fire_filename=self.pair(root),
                    now=T+timedelta(minutes=5)),("ready",0))

    @staticmethod
    def _status():
        return "flat_verified"

    def test_rejected_no_order_after_close_does_not_reset_cooldown(self):
        close=(T-timedelta(hours=1),T,"flat_verified",self.closed())
        rejected=(T+timedelta(seconds=15),T+timedelta(seconds=15),
                  "rejected_no_order",{"orders_submitted":False})
        write_db(self.gold,self.pair(self.gold),[close,rejected])
        self.assertEqual(post_close_cooldown(
            self.gold,fire_filename=self.pair(self.gold),
            now=T+timedelta(seconds=30)),("cooling_down",270))

    def test_close_timestamp_required_and_future_fails_closed(self):
        for record in (
            (T,T+timedelta(minutes=1),"flat_verified",self.closed()),
            (T,T,"flat_verified",self.closed(False)),
            (T,T,"flat_verified",
             dict(self.closed(),reason_code="emergency_flat_verified")),
        ):
            with self.subTest(record=record[2:]):
                root=self.gold
                db=root/self.pair(root)
                if db.exists():db.unlink()
                write_db(root,self.pair(root),[record])
                self.assertEqual(post_close_cooldown(
                    root,fire_filename=self.pair(root),now=T),
                    ("unavailable",None))

    def test_wrong_account_missing_or_bad_db_fails_closed(self):
        self.assertEqual(post_close_cooldown(
            self.gold,fire_filename="fire-ops.sqlite",now=T),
            ("unavailable",None))
        self.assertEqual(post_close_cooldown(
            self.gold,fire_filename=self.pair(self.gold),now=T),
            ("unavailable",None))
        write_db(self.gold,self.pair(self.gold),[
            (T,T,"flat_verified",self.closed())])
        db=self.gold/self.pair(self.gold)
        db.unlink()
        db.symlink_to(self.base/"nonexistent-target")
        self.assertEqual(post_close_cooldown(
            self.gold,fire_filename=self.pair(self.gold),now=T),
            ("unavailable",None))

    def test_workers_skip_cooling_down_without_spending_attempt(self):
        for root,runner in ((self.btc,btc_run),(self.gold,gold_run)):
            with self.subTest(root=root):
                write_db(root,self.pair(root),[
                    (T-timedelta(hours=1),T,"flat_verified",self.closed())])
                run_kwargs={
                    "instant":T+timedelta(minutes=3),
                    "armed":lambda:True,
                    "candidate":lambda root:True,
                    "do_execute":True,
                }
                if root==self.btc:
                    run_kwargs["receipts_safe"]=lambda root:True
                else:
                    run_kwargs["receipt_check"]=lambda root:True
                out=runner(root,**run_kwargs)
                self.assertEqual(out["status"],"post_trade_cooldown")
                self.assertEqual(out["remaining_seconds"],120)
                attempt_db=root/("btc-auto-demo.sqlite" if root==self.btc
                                 else "gold-auto-demo.sqlite")
                self.assertFalse(attempt_db.exists())

    def test_worker_rejects_unreadable_close_record_without_model(self):
        root=self.gold
        write_db(root,self.pair(root),[
            (T,T,"flat_verified",self.closed(False))])
        out=gold_run(root,instant=T,armed=lambda:True,
                     candidate=lambda _:True,
                     receipt_check=lambda _:True,
                     do_execute=True)
        self.assertEqual(out["status"],"verified_trade_close_time_unavailable")
        self.assertFalse((root/"gold-auto-demo.sqlite").exists())


if __name__=="__main__":
    unittest.main()
