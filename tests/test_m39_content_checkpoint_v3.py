import json,sqlite3,shutil,tempfile,unittest
from pathlib import Path
from contextlib import closing
from tradebot.m39_equity_state_fixture_v3 import replay,history_checkpoint,verify_checkpoint,canonical,digest
from test_m25_equity_policy_research_v3 import fixture,val

class ContentCheckpoint(unittest.TestCase):
    def setUp(self):
        d=tempfile.TemporaryDirectory();self.addCleanup(d.cleanup);self.p=Path(d.name)/'m39-fixture.sqlite';self.w=Path(d.name)/'retained.json'
        self.f=fixture(val(1,'100'),val(2,'80'));replay(self.p,self.f)
        self.w.write_text(json.dumps(history_checkpoint(self.p)))
    def verify(self):return verify_checkpoint(self.p,json.loads(self.w.read_text()))
    def test_unchanged(self):self.assertTrue(self.verify())
    def test_equal_count_rewrite(self):
        body=canonical(val(2,'99'))
        with closing(sqlite3.connect(self.p)) as db,db:db.execute('UPDATE fixture_events SET body=?,sha=? WHERE seq=1',(body,digest(body)))
        with self.assertRaises(ValueError):self.verify()
    def test_missing(self):
        self.p.unlink()
        with self.assertRaises(ValueError):self.verify()
    def test_rollback(self):
        old=self.p.with_name('old.sqlite');shutil.copy2(self.p,old)
        self.f['events'].append(val(3,'60'));replay(self.p,self.f);self.w.write_text(json.dumps(history_checkpoint(self.p)))
        shutil.copy2(old,self.p)
        with self.assertRaises(ValueError):self.verify()
    def test_cross_market_change(self):
        g=fixture(val(1,'100'));g.update(symbol='XAUTUSD',fixture_account='synthetic-gold');g['events'][0].update(symbol='XAUTUSD',fixture_account='synthetic-gold');replay(self.p,g)
        with self.assertRaises(ValueError):self.verify()
