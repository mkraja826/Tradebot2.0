import unittest
from decimal import Decimal
from tradebot.margin_reference_v3 import compare
class MarginReferenceTests(unittest.TestCase):
    def test_four_order_types(self):
        f=dict(mark='105',bid='100',ask='101',unit='0.001',contracts=1,initial_margin_fraction='0.05')
        for side,kind,limit,base in [('LONG','MARKET',None,'105'),('SHORT','MARKET',None,'105'),('LONG','LIMIT','98','98'),('SHORT','LIMIT','98','100')]:
            r=compare(**f,side=side,kind=kind,limit=limit)
            self.assertEqual(Decimal(r['documented_initial_margin']),Decimal(base)*Decimal('0.00005'))
            self.assertFalse(r['execution_authorized'])
            self.assertFalse(r['broker_quote_verified'])
        r=compare(**dict(f,mark='99'),side='SHORT',kind='MARKET',limit=None)
        self.assertEqual(r['documented_price_basis'],'100')
    def test_invalid(self):
        f=dict(side='LONG',kind='MARKET',mark='105',bid='100',ask='101',limit=None,unit='0.001',contracts=1,initial_margin_fraction='0.05')
        for k,v in [('contracts',0),('mark','NaN'),('initial_margin_fraction','2'),('ask','99'),('limit','100')]:
            with self.assertRaises(ValueError):compare(**dict(f,**{k:v}))

    def test_tier_fee_fixture(self):
        from tradebot.margin_reference_v3 import tier_fee_fixture
        f=dict(side='LONG',kind='MARKET',mark='100',bid='99',ask='101',limit=None,
            unit='1',contracts=2,minimum_margin_pct='1',threshold_usd='100',
            slope_pct_per_usd='0.1',selected_leverage=20,entry_fee_fraction='0.001',
            exit_fee_fraction='0.001',estimated_exit_price='90')
        r=tier_fee_fixture(**f)
        self.assertEqual(Decimal(r['tier_margin_fraction']),Decimal('0.11'))
        self.assertEqual(Decimal(r['estimated_initial_margin']),Decimal('22'))
        self.assertEqual(Decimal(r['estimated_fee_reserve']),Decimal('0.382'))
        self.assertEqual(Decimal(r['estimated_total_reserve']),Decimal('22.382'))
        self.assertFalse(r['execution_authorized'])
        for t in ('200','300'):
            r=tier_fee_fixture(**dict(f,threshold_usd=t))
            self.assertEqual(Decimal(r['estimated_initial_margin']),Decimal('10'))
        for k,v in [('selected_leverage',0),('slope_pct_per_usd','-1'),('exit_fee_fraction','0.1')]:
            with self.assertRaises(ValueError):tier_fee_fixture(**dict(f,**{k:v}))
