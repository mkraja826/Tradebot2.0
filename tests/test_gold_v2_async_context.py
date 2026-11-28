import unittest
from concurrent.futures import Future
from unittest.mock import Mock,patch
from recover_trading.gold_v2_hybrid_worker import Study
from recover_trading.gold_v2_hybrid import MARK_SOURCE
from recover_trading.gold_v2_mark_context import ContextCollector

NOW=3600020
class AsyncContextTests(unittest.TestCase):
    def test_slow_macro_does_not_delay_reference_or_quotes(self):
        j=Mock();j.summary.return_value={}
        demo=Mock();ref=Mock();p=Mock();m=Mock()
        p.submit.return_value=Future();m.submit.return_value=Future()
        s=Study(j,demo,ref,{"id":42},{"id":43},clock=lambda:NOW,source=MARK_SOURCE)
        s.cycle(p,m);s.cycle(p,m)
        self.assertEqual(j.record_quote.call_count,2)
        self.assertEqual(p.submit.call_count,1)
        self.assertEqual(m.submit.call_count,1)
        self.assertIsNone(s.macro_snapshot)
    def test_failed_macro_refresh_keeps_quotes(self):
        j=Mock();j.summary.return_value={}
        p=Mock();m=Mock();p.submit.return_value=Future()
        f=Future();f.set_exception(TimeoutError());m.submit.return_value=f
        s=Study(j,Mock(),Mock(),{"id":42},{"id":43},clock=lambda:NOW,source=MARK_SOURCE)
        s.cycle(p,m);x=s.cycle(p,m)
        self.assertEqual(x["errors"]["macro_refresh"],"TimeoutError")
        self.assertEqual(j.record_quote.call_count,2)
    def test_snapshot_age(self):
        c=ContextCollector(external=Mock(),feeds=Mock(),clock=lambda:NOW)
        for snapshot in (None,{"observed_at":NOW-301},{"observed_at":NOW+1}):
            self.assertIsNone(c.project({"signal_source":MARK_SOURCE},snapshot))
        c.external.assert_not_called()
