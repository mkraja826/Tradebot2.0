import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from recover_trading.gold_v2_reference import observe_reference,SOURCE
from recover_trading.gold_v2_entry_adapter import select
from recover_trading.gold_v2_validation import Journal

NOW=3600020
class Fixture:
    def __init__(self,spike=False):self.spike=spike
    def candles(self,*,symbol,resolution,start,end):
        assert symbol=="XAUTUSD"
        step={"5m":300,"15m":900,"1h":3600}[resolution]
        rows=[]
        for i,t in enumerate(range(start,end,step)):
            p=100+i*.01
            rows.append({"time":t,"open":p,"high":p+1,"low":p-1,"close":p+.1,"volume":10})
        if self.spike and resolution=="15m":rows[100]["high"]+=100
        return rows

class ReferenceTests(unittest.TestCase):
    def test_reference_provenance(self):
        packet=observe_reference(NOW,client=Fixture())
        self.assertEqual(packet["status"],"reference_research_only")
        report=packet["strict_reference_report"]
        self.assertEqual(report["status"],"observed")
        self.assertEqual(report["signal_source"],SOURCE)
        self.assertFalse(report["execution_eligible"])
        self.assertEqual(select(report),(None,"reference_research_only"))
        with TemporaryDirectory() as t:
            j=Journal(Path(t)/"validation.sqlite",clock=lambda:NOW)
            try:
                with self.assertRaisesRegex(ValueError,"reference_report_requires_separate_validation"):j.enroll(report)
            finally:j.close()
    def test_anomaly_not_overridden(self):
        packet=observe_reference(NOW,client=Fixture(spike=True))
        report=packet["strict_reference_report"]
        self.assertEqual(report["status"],"data_unusable")
        self.assertEqual(report["candidates"],[])
        self.assertEqual(packet["close_diagnostics"]["900"]["true_range_anomalies"],1)
    def test_missing_frames(self):
        class Missing:
            def candles(self,**kw):return []
        packet=observe_reference(NOW,client=Missing())
        self.assertEqual(packet["strict_reference_report"]["status"],"data_unusable")
        self.assertEqual(packet["close_diagnostics"],{})
