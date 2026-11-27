import json
import tempfile
import threading
import unittest
from pathlib import Path
from recover_trading.gold_v2_worker import Worker,account_snapshot

NOW=3600020
def scanner(client,stamp,**kw):
    return {"symbol":"XAUTUSD","as_of":stamp,"status":"observed","version":"fixture",
            "candidates":[],"feed_health":{"5m":"ready"}}
def collector(client,symbol,**kw):
    return {"symbol":symbol,"as_of":kw["as_of"],"frames":{"5m":{"status":"unavailable"}}}
class Reader:
    def wallet(self):return {"result":[{"asset_symbol":"USD","user_id":"123","balance":"100","available_balance":"80"}]}
    def product(self,symbol):return {"symbol":symbol,"id":42,"contract_unit_currency":"XAUT","settling_asset":{"symbol":"USD"},
                                   "quoting_asset":{"symbol":"USD"},"notional_type":"vanilla"}
    def margined_positions(self,pid):return []
    def active_orders_page(self,pid,after=None):return {"result":[],"meta":{}}
class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def worker(self,**kw):
        args=dict(scanner=scanner,collector=collector,clock=lambda:NOW)
        args.update(kw)
        return Worker(self.root,None,**args)
    def test_once_publishes_separate_status(self):
        legacy=self.root/"status.json";legacy.write_text("legacy")
        w=self.worker();w.run(threading.Event(),60,once=True)
        self.assertEqual(legacy.read_text(),"legacy")
        x=json.loads((self.root/"gold_v2_status.json").read_text())
        self.assertEqual(x["mode"],"shadow")
        self.assertEqual(x["execution_effect"],"none")
        self.assertFalse(x["execution_enabled"])
        self.assertEqual(x["enrollment"]["status"],"no_candidate")
    def test_single_worker_lock(self):
        w=self.worker();other=self.worker()
        w.open()
        try:
            with self.assertRaises(BlockingIOError):other.open()
        finally:w.close()
        other.open();other.close()
    def test_persistence(self):
        self.worker().run(threading.Event(),60,once=True)
        self.worker().run(threading.Event(),60,once=True)
        x=json.loads((self.root/"gold_v2_status.json").read_text())
        self.assertEqual(x["enrollment"]["status"],"duplicate")
    def test_scan_error_does_not_prevent_resolution(self):
        seen=[]
        def broken(*a,**k):raise RuntimeError("private detail")
        def collect(*a,**k):
            seen.append(True);return collector(*a,**k)
        w=self.worker(scanner=broken,collector=collect)
        w.run(threading.Event(),60,once=True)
        x=json.loads((self.root/"gold_v2_status.json").read_text())
        self.assertTrue(seen)
        self.assertEqual(x["status"],"degraded")
        self.assertEqual(x["errors"]["scan_or_enrollment"],"RuntimeError")
        self.assertNotIn("private detail",json.dumps(x))
    def test_account_read(self):
        v=account_snapshot(Reader(),"123",clock=lambda:NOW)
        self.assertEqual(v["position_state"],"flat")
        self.assertEqual(v["bracket_state"],"no_orders_observed")
    def test_account_mismatch(self):
        with self.assertRaises(ValueError):account_snapshot(Reader(),"456",clock=lambda:NOW)
    def test_account_status_no_wallet_data(self):
        w=self.worker(broker=Reader(),expected_account="123")
        w.run(threading.Event(),60,once=True)
        x=json.loads((self.root/"gold_v2_status.json").read_text())
        self.assertEqual(x["account"]["position_state"],"flat")
        self.assertNotIn("user_id",json.dumps(x))
        self.assertNotIn("balance",json.dumps(x))
    def test_allocation_requires_reader(self):
        with self.assertRaises(ValueError):self.worker(allocation_fraction=.1)
    def test_invalid_interval(self):
        with self.assertRaises(ValueError):self.worker().run(threading.Event(),0)
