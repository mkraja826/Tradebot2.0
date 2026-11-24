import unittest
from copy import deepcopy
from decimal import Decimal
from tradebot.equity_policy_v3 import account_research,compare_accounts
from test_m25_equity_policy_research_v3 import fixture,val,flow

def pair(*events):
    btc=fixture(*events)
    gold=deepcopy(fixture(val(1,'100'),val(2,'97')))
    gold.update(symbol='XAUTUSD',fixture_account='synthetic-gold')
    for e in gold['events']:e.update(symbol='XAUTUSD',fixture_account='synthetic-gold')
    return dict(BTCUSD=btc,XAUTUSD=gold)

class NativeEquityResearch(unittest.TestCase):
    def test_independent_histories(self):
        r=compare_accounts(pair(val(1,'100'),val(2,'105')))
        self.assertEqual(Decimal(r['markets']['BTCUSD']['maximum_observed_drawdown']),0)
        self.assertEqual(Decimal(r['markets']['XAUTUSD']['maximum_observed_drawdown']),Decimal('0.03'))
        self.assertFalse(r['execution_authorized'])
    def test_recovery_preserves_maximum_loss(self):
        r=account_research(fixture(val(1,'100'),val(2,'80'),val(3,'105')))
        self.assertEqual(Decimal(r['maximum_observed_drawdown']),Decimal('0.2'))
        self.assertEqual(Decimal(r['observed_peak_decline']),0)
    def test_transfer_does_not_mask_loss(self):
        r=account_research(fixture(val(1,'100'),val(2,'90'),flow(3,'90','190','100')))
        self.assertEqual(Decimal(r['maximum_observed_drawdown']),Decimal('0.1'))
    def test_pure_outflow(self):
        r=account_research(fixture(val(1,'100'),flow(2,'100','40','-60')))
        self.assertEqual(Decimal(r['maximum_observed_drawdown']),0)
    def test_loss_at_transfer_boundary(self):
        r=account_research(fixture(val(1,'100'),flow(2,'80','130','50')))
        self.assertEqual(Decimal(r['maximum_observed_drawdown']),Decimal('0.2'))
    def test_incomplete(self):
        f=fixture(val(1,'100'));f['complete_fixture']=False
        self.assertIsNone(account_research(f)['maximum_observed_drawdown'])
    def test_missing_market(self):
        with self.assertRaises(ValueError):compare_accounts(dict(BTCUSD=fixture(val(1,'100'))))
    def test_main_not_supported(self):
        f=pair(val(1,'100'));f['MAIN']=f['BTCUSD']
        with self.assertRaises(ValueError):compare_accounts(f)
    def test_duplicate_account(self):
        f=pair(val(1,'100'));f['XAUTUSD']['fixture_account']=f['BTCUSD']['fixture_account']
        with self.assertRaises(ValueError):compare_accounts(f)
    def test_wrong_market(self):
        f=pair(val(1,'100'));f['BTCUSD']['symbol']='XAUTUSD'
        with self.assertRaises(ValueError):compare_accounts(f)
    def test_live_refused(self):
        f=fixture(val(1,'100'));f['mode']='live'
        with self.assertRaises(ValueError):account_research(f)
