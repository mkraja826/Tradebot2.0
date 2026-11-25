import unittest
from recover_trading.gold_release_research import normalize,evaluate,epoch,probe
class GoldReleaseTests(unittest.TestCase):
    def fixture(self):
        return {"rule":"G20","measure":"cpi_mom_sa_pct","reference_month":"2026-10","release_at":"2026-11-10T13:30:00Z","value":"0.3","source_url":"https://example.org/forecast"}
    def test_timing_and_surprise(self):
        f=self.fixture();t=epoch(f["release_at"])
        x=normalize(f,"forecast",t-1)
        y=normalize({**f,"value":"0.4","source_url":"https://www.bls.gov/news.release/archives/cpi_11102026.htm"},"actual",t+1)
        r=evaluate(x,y,t+2)
        self.assertEqual(r["surprise"],"0.1")
        self.assertEqual(r["status"],"paired_operator_evidence_unverified")
        self.assertIsNone(r["direction"])
        with self.assertRaises(ValueError):normalize(f,"forecast",t)
        with self.assertRaises(ValueError):normalize(f,"actual",t-1)
        self.assertEqual(evaluate(x,{**y,"reference_month":"2026-09"},t+2)["status"],"event_identity_mismatch")
    def test_feed_failure(self):
        def fail(url):raise TimeoutError()
        r=probe(fail)
        self.assertEqual(r["sources"]["G20"]["status"],"source_unavailable")
        self.assertEqual(r["sources"]["G21"]["consensus_status"],"not_connected")
