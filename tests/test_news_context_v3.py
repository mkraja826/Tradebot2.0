import unittest
from datetime import datetime,timezone
from tradebot.news_context_v3 import parse,fomc_active
from tradebot.gold_strategies_v3 import RULES,evaluate
NOW=datetime(2026,11,24,19,20,tzinfo=timezone.utc)
T=NOW.timestamp()
RSS="""<rss><channel><item><title>Minutes of the Federal Open Market Committee</title><pubDate>Tue, 24 Nov 2026 19:15:00 GMT</pubDate></item><item><title>Federal Reserve issues FOMC statement</title><pubDate>Tue, 24 Nov 2026 19:00:00 GMT</pubDate><link>https://www.federalreserve.gov/newsevents/pressreleases/monetary20261124a.htm</link></item></channel></rss>"""
class NewsTests(unittest.TestCase):
    def test_fomc_post_release_only(self):
        d=parse(RSS,"fomc_release",NOW); item={"status":"ready","observed_at":T-60,"data":d}
        self.assertEqual(fomc_active(item,now=T,closed_at=T-300,frame_seconds=900),1)
        self.assertEqual(fomc_active(item,now=T,closed_at=T-1200,frame_seconds=900),0)
        self.assertIsNone(fomc_active(item,now=T+500,closed_at=T-300,frame_seconds=900))
        self.assertEqual(fomc_active(dict(item,observed_at=T+3600),now=T+3600,closed_at=T+3300,frame_seconds=900),0)
        rule=next(r for r in RULES if r.id=="G22")
        self.assertEqual(evaluate(rule,dict(fomc_post_statement=1,close=9,open=11,ema9=10,rvol20=2,body_fraction=.8))["directions"],["SHORT"])
    def test_bls_timestamp_is_not_release_verification(self):
        a='<feed xmlns="http://www.w3.org/2005/Atom"><id>bls.gov:feed:cpi</id><entry><title>Inflation</title><link href="https://www.bls.gov/news.release/archives/cpi_11242026.htm"/><published>2026-11-24T12:55:00Z</published><content>Actual release summary</content></entry></feed>'
        r=parse(a,"cpi_release",NOW)
        self.assertFalse(r["release_time_verified"]); self.assertIsNone(r["consensus"])
        with self.assertRaises(ValueError): parse(a,"nfp_release",NOW)
        with self.assertRaises(ValueError): parse('<!DOCTYPE x>'+a,"cpi_release",NOW)
