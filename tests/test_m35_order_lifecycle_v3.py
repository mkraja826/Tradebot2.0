"""M35.2 offline MARKET lifecycle evidence, not broker authorization."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import closing
import sqlite3
import unittest
from unittest.mock import patch
from tradebot.synthetic_lifecycle_v3 import LifecycleLedger, fixture_receipt, fixture_protections
from test_m23_limit_lifecycle_v3 import preview

class MarketLifecycleTests(unittest.TestCase):
    def setUp(self):
        t=TemporaryDirectory(); self.addCleanup(t.cleanup)
        self.path=Path(t.name)/'market.sqlite'
        self.p=preview(); self.p['entry']['kind']='MARKET'
        self.l=LifecycleLedger(self.path)
        self.assertEqual(self.l.reserve(self.p),'reserved')

    def put(self,q,state,t,protection=None):
        b=fixture_protections(self.p,q) if q else []
        return self.l.observe(self.p,fixture_receipt(self.p,q,state),b if protection is None else protection,stamp=t)

    @patch('socket.socket',side_effect=AssertionError('offline only'))
    def test_restart_after_unknown_ack(self,network):
        r=self.l.observe(self.p,None,[],stamp=1)
        self.assertEqual(r['entry_state'],'unknown_requires_reconciliation')
        self.l=LifecycleLedger(self.path)
        self.assertEqual(self.l.reserve(self.p),'already_reserved')
        r=self.put(1,'open',2)
        self.assertEqual(r['filled_contracts'],1)
        self.assertFalse(r['execution_authorized'])
        self.assertFalse(r['broker_verified'])
        network.assert_not_called()

    def test_partial_growth(self):
        self.put(1,'open',1)
        r=self.put(2,'open',2,fixture_protections(self.p,1))
        self.assertEqual(r['protection_state'],'fixture_protection_unverified')
        self.assertEqual(self.put(2,'open',3)['protection_state'],'fixture_bracket_matched')
        self.assertEqual(self.put(3,'closed',4)['entry_state'],'fixture_filled')

    def test_unknown_preserves_fill(self):
        self.put(2,'open',1)
        self.l.observe(self.p,None,[],stamp=2)
        self.l=LifecycleLedger(self.path)
        with self.assertRaisesRegex(ValueError,'decreasing_fill'): self.put(1,'open',3)
        with self.assertRaises(ValueError): self.put(0,'rejected',3)
        self.assertEqual(self.put(3,'closed',4)['filled_contracts'],3)

    def test_terminal_and_duplicate(self):
        self.put(3,'closed',1)
        self.assertEqual(self.put(3,'closed',1),'duplicate')
        with self.assertRaisesRegex(ValueError,'conflicting_observation'): self.put(3,'closed',1,[])
        self.l.observe(self.p,None,[],stamp=2)
        with self.assertRaises(ValueError): self.put(2,'open',3)
        with self.assertRaisesRegex(ValueError,'out_of_order'): self.put(3,'closed',1)

    def test_conflicting_reservation(self):
        p=deepcopy(self.p); p['entry']['contracts']=4
        with self.assertRaisesRegex(ValueError,'conflicting_preview'): self.l.reserve(p)
        with self.assertRaisesRegex(ValueError,'unreserved_preview'): self.l.observe(p,None,[],stamp=1)

    def test_wrong_identity_and_overfill(self):
        for t,(field,value) in enumerate([('symbol','XAUTUSD'),('client_order_id','other'),('product_id',999),('side','sell'),('filled_contracts',4),('source','broker')],1):
            r=fixture_receipt(self.p,1,'open'); r[field]=value
            with self.subTest(field=field):
                x=self.l.observe(self.p,r,[],stamp=t)
                self.assertIsNone(x['filled_contracts'])
                self.assertFalse(x['execution_authorized'])

    def test_rejection_and_append_only(self):
        self.assertEqual(self.put(0,'rejected',1)['protection_state'],'not_required')
        with self.assertRaises(ValueError): self.put(1,'open',2)
        with closing(self.l.connect()) as db,db:
            with self.assertRaises(sqlite3.IntegrityError): db.execute('DELETE FROM observations')
