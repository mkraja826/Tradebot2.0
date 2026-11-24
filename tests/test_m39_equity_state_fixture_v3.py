import unittest,tempfile,json,subprocess,sys
from pathlib import Path
from decimal import Decimal
from tradebot.m39_equity_state_fixture_v3 import replay
from test_m25_equity_policy_research_v3 import fixture,val,flow

class DurableFixture(unittest.TestCase):
    def setUp(self):
        self.d=tempfile.TemporaryDirectory();self.addCleanup(self.d.cleanup);self.p=Path(self.d.name)/'m39-fixture.sqlite'
    def test_restart_and_recovery(self):
        f=fixture(val(1,'100'),val(2,'80'));replay(self.p,f)
        f['events']+= [flow(3,'80','180','100'),val(4,'240')]
        code='import sys,json;from tradebot.m39_equity_state_fixture_v3 import replay;print(json.dumps(replay(sys.argv[1],json.loads(sys.argv[2]))))'
        r=json.loads(subprocess.check_output([sys.executable,'-B','-c',code,str(self.p),json.dumps(f)],text=True))
        self.assertEqual(Decimal(r['maximum_observed_drawdown']),Decimal('.2'));self.assertEqual(r['new_events'],2);self.assertFalse(r['execution_authorized']);self.assertEqual(replay(self.p,f)['new_events'],0)
    def test_rewrite_and_truncate(self):
        f=fixture(val(1,'100'),val(2,'80'));replay(self.p,f)
        for bad in (fixture(val(1,'100')),fixture(val(1,'100'),val(2,'90'))):
            with self.assertRaises(ValueError):replay(self.p,bad)
        self.assertEqual(replay(self.p,f)['new_events'],0)
    def test_mismatch_and_live(self):
        with self.assertRaises(ValueError):replay(self.p,dict(fixture(val(1,'100')),mode='live'))
        with self.assertRaises(ValueError):replay(self.p,dict(fixture(val(1,'100')),fixture_account='synthetic-gold'))
    def test_invalid_transfer(self):
        f=fixture(val(1,'100'));replay(self.p,f)
        with self.assertRaises(ValueError):replay(self.p,fixture(val(1,'100'),flow(2,'100','150','49')))
        self.assertEqual(replay(self.p,f)['new_events'],0)
