import unittest
import json
from concurrent.futures import Future
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import Mock
from recover_trading.gold_v2_hybrid_worker import Study,publish
from recover_trading.gold_v2_dashboard import read_hybrid_status

NOW=3600020
class WorkerTests(unittest.TestCase):
    def test_reference_pending_does_not_interrupt_demo_quote(self):
        journal=Mock();journal.summary.return_value={}
        demo=Mock();demo.ticker.return_value={"symbol":"XAUTUSD"}
        ref=Mock();pool=Mock();pool.submit.return_value=Future()
        s=Study(journal,demo,ref,{"id":42},{"id":43},clock=lambda:NOW)
        s.cycle(pool);s.cycle(pool)
        self.assertEqual(pool.submit.call_count,1)
        self.assertEqual(journal.record_quote.call_count,2)
        ref.ticker.assert_not_called()
    def test_reference_failure_does_not_interrupt_demo_quote(self):
        j=Mock();j.summary.return_value={}
        d=Mock();p=Mock();f=Future();f.set_exception(TimeoutError())
        p.submit.return_value=f
        s=Study(j,d,Mock(),{"id":42},{"id":43},clock=lambda:NOW)
        s.cycle(p);x=s.cycle(p)
        self.assertEqual(x["errors"]["reference"],"TimeoutError")
        self.assertEqual(j.record_quote.call_count,2)
    def test_status_independent_of_demo_worker(self):
        with TemporaryDirectory() as t:
            root=Path(t)
            publish(root,{"symbol":"XAUTUSD","mode":"hybrid_research_only","timestamp":NOW,
                "summary":{"quote_count":9,"actual_fills":99,"sampled_comparisons":[{"family":"fixture","direction":"LONG","samples":1,"positive_samples":1,"mean_sampled_net_bps":10,"secret":"never"}]},
                "latest_signal":{"reference_status":"data_unusable","signal_observed_at":NOW-5}})
            result=read_hybrid_status(root,NOW)
            self.assertEqual(result["status"],"observed")
            self.assertEqual(result["actual_fills"],0)
            self.assertEqual(result["quote_count"],9)
            self.assertNotIn("secret",result["sampled_comparisons"][0])
            self.assertEqual(read_hybrid_status(root,NOW+61)["status"],"stale")
            self.assertEqual(read_hybrid_status(root,NOW-1)["status"],"unavailable")
