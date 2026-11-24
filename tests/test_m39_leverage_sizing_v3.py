import unittest
from decimal import Decimal
from tradebot.m27_sizing_research_v3 import review,quantity_bound_fixture
from test_m27_sizing_research_v3 import fixture,NOW
class LeverageSizing(unittest.TestCase):
    def test_margin_changes_not_loss(self):
        for s in ('BTCUSD','XAUTUSD'):
            for side in ('LONG','SHORT'):
                a=review(dict(fixture(s,side),fixture_leverage=5),now=NOW)
                b=review(dict(fixture(s,side),fixture_leverage=20),now=NOW)
                self.assertLess(Decimal(b['estimated_margin_with_costs']),Decimal(a['estimated_margin_with_costs']))
                self.assertEqual(a['estimated_stop_loss'],b['estimated_stop_loss']);self.assertFalse(b['execution_authorized'])
    def test_invalid_leverage(self):
        for v in (0,21,True,2.5,'20'):
            with self.assertRaises(ValueError):review(dict(fixture(),fixture_leverage=v),now=NOW)
    def test_cushion_preserved(self):
        r=review(dict(fixture(),fixture_leverage=20,stop_loss='980'),now=NOW)
        self.assertEqual(r['status'],'existing_risk_validator_rejected_fixture')
    def test_loss_budget_preserved(self):
        a=quantity_bound_fixture(dict(fixture(),fixture_equity='10',fixture_available_margin='10',fixture_leverage=5),now=NOW,contract_ceiling=1200)
        b=quantity_bound_fixture(dict(fixture(),fixture_equity='10',fixture_available_margin='10',fixture_leverage=20),now=NOW,contract_ceiling=1200)
        self.assertEqual(a['estimated_quantity_upper_bound'],b['estimated_quantity_upper_bound']);self.assertFalse(b['execution_authorized'])
