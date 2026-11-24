import unittest
from tradebot.m27_sizing_research_v3 import quantity_bound_fixture
from test_m27_sizing_research_v3 import fixture,NOW

class QuantityBound(unittest.TestCase):
    def test_cap(self):
        for s in ('BTCUSD','XAUTUSD'):
            for side in ('LONG','SHORT'):
                r=quantity_bound_fixture(fixture(s,side),now=NOW,contract_ceiling=7)
                self.assertEqual(r['estimated_quantity_upper_bound'],7);self.assertFalse(r['execution_authorized'])
    def test_margin(self):
        r=quantity_bound_fixture(dict(fixture(),fixture_available_margin='1'),now=NOW,contract_ceiling=1200)
        self.assertEqual(r['estimated_quantity_upper_bound'],4)
    def test_risk(self):
        r=quantity_bound_fixture(dict(fixture(),fixture_equity='10',fixture_available_margin='10'),now=NOW,contract_ceiling=1200)
        self.assertEqual(r['estimated_quantity_upper_bound'],2)
    def test_no_margin(self):
        r=quantity_bound_fixture(dict(fixture(),fixture_available_margin='0'),now=NOW,contract_ceiling=1200)
        self.assertEqual(r['estimated_quantity_upper_bound'],0)
    def test_nonfixture(self):
        with self.assertRaises(ValueError):quantity_bound_fixture(dict(fixture(),mode='live'),now=NOW,contract_ceiling=7)
