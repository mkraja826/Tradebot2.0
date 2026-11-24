import unittest,json,sqlite3
from contextlib import closing
from tempfile import TemporaryDirectory
from pathlib import Path
from tradebot.opportunity_journal_v3 import OpportunityJournal
from tradebot.shadow_dispatch_v3 import tick as dispatch,store_fixture
from tradebot.ai_decision_v3 import prepare
from tradebot.ai_replay_v3 import wait_fixture
from tradebot.decision_experience_v3 import tick,project
from test_opportunity_scanner_v3 import NOW,scan,ctx
class DecisionExperienceTests(unittest.TestCase):
    def test_capture_and_observation_progress(self):
        with TemporaryDirectory() as d:
            p=Path(d); j=OpportunityJournal(p/"opportunities-v3.sqlite")
            c=dict(ctx(),context_observed_at=NOW,market={"frames":{}})
            e=j.record(scan(),c)
            dispatch(p,now=NOW)
            with closing(sqlite3.connect(p/"market-v3.sqlite")) as db,db:
                db.execute("CREATE TABLE samples(symbol,series,stamp,payload)")
                for t in range(NOW+300,NOW+14700,300):
                    bar=dict(time=t,open=100,high=102,low=99,close=101,volume=10)
                    db.execute("INSERT INTO samples VALUES(?,?,?,?)",("BTCUSD","candle:5m",t,json.dumps(bar)))
            r=tick(p,now=NOW)
            self.assertEqual(r["ingested"],1)
            self.assertEqual(r["markets"]["BTCUSD"]["recent_exact_requests"],1)
            self.assertEqual(r["markets"]["BTCUSD"]["pending_events"],1)
            r=tick(p,now=NOW+1200);self.assertEqual(r["new_observations"],1)
            r=tick(p,now=NOW+14700);self.assertEqual(r["new_observations"],2)
            self.assertEqual(r["markets"]["BTCUSD"]["pending_events"],0)
            r=tick(p,now=NOW+15000)
            self.assertEqual((r["ingested"],r["new_observations"]),(0,0))
            with closing(sqlite3.connect(p/"decision-experience-v3.sqlite")) as db:
                self.assertEqual(db.execute("select count(*) from observations").fetchone()[0],3)
                a=json.loads(db.execute("select payload from observations limit 1").fetchone()[0])
                self.assertFalse(a["actual_trade_outcome"])
                with self.assertRaises(sqlite3.IntegrityError): db.execute("delete from decisions")
                with self.assertRaises(sqlite3.IntegrityError): db.execute("update observations set payload='{}'")
    def test_legacy_and_tamper(self):
        with TemporaryDirectory() as d:
            p=Path(d); e=OpportunityJournal(p/"events.sqlite").record(scan(),ctx()); q=prepare(e); a=wait_fixture(q)
            store_fixture(p/"old.sqlite",e,q,a)
            with closing(sqlite3.connect(p/"old.sqlite")) as db: r=json.loads(db.execute("select payload from decisions").fetchone()[0])
            x=project(e,r,"BTCUSD",e["event_id"],now=NOW)
            self.assertEqual(x["request_provenance"],"reconstructed_payload_verified")
            self.assertIsNone(x["recorded_at"])
            r["response_sha256"]="bad"
            with self.assertRaises(ValueError): project(e,r,"BTCUSD",e["event_id"],now=NOW)
