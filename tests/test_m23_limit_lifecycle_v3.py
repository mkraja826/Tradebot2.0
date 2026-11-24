from contextlib import closing
import unittest,tempfile,sqlite3
from pathlib import Path
from tradebot.m23_limit_lifecycle_v3 import LimitLedger
from tradebot.synthetic_lifecycle_v3 import fixture_receipt,fixture_protections

def preview(symbol="BTCUSD",action="LONG"):
    return dict(mode="synthetic_execution_preview",symbol=symbol,event_id="fixture-"+symbol+action,execution_authorized=False,orders_submitted=0,action=action,entry=dict(kind="LIMIT",contracts=3,side="buy" if action=="LONG" else "sell",product_id=84 if symbol=="BTCUSD" else 181689,preview_client_id="fixture-id"),protection=dict(stop_loss="90" if action=="LONG" else "110",take_profit="110" if action=="LONG" else "90"))

class LimitTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"fixture.sqlite"
        self.p=preview();self.l=LimitLedger(self.path)
        self.l.reserve(self.p,now=100,expires=150)
    def put(self,q,state,t,brackets=None):
        return self.l.observe(self.p,fixture_receipt(self.p,q,state),fixture_protections(self.p,q) if brackets is None and q else brackets or [],stamp=t)
    def test_expiry_not_cancellation(self):
        self.put(0,"open",101)
        r=self.l.status(self.p,now=151)
        self.assertTrue(r["cancellation_required"]);self.assertEqual(r["state"],"open")
        self.assertFalse(r["retry_authorized"])
        r=self.put(0,"cancelled",152)
        self.assertTrue(r["cancellation_confirmed"])
    def test_partial_cancel_and_recovery(self):
        self.put(1,"open",101)
        r=self.put(2,"open",102,fixture_protections(self.p,1))
        self.assertEqual(r["protection"],"fixture_protection_unverified")
        self.l.observe(self.p,None,[],stamp=103)
        self.l=LimitLedger(self.path)
        self.assertEqual(self.l.reserve(self.p,now=104,expires=150),"already_reserved")
        r=self.l.status(self.p,now=104)
        self.assertEqual(r["last_known_filled"],2);self.assertTrue(r["reconciliation_required"])
        r=self.put(2,"cancelled",105)
        self.assertEqual(r["filled"],2);self.assertEqual(r["remaining"],0)
        self.assertEqual(r["protection"],"fixture_bracket_matched")
        with self.assertRaises(ValueError):self.put(3,"filled",106)
    def test_fills_and_duplicates(self):
        self.put(1,"open",101)
        with self.assertRaises(ValueError):self.put(0,"open",102)
        self.put(3,"filled",103)
        self.assertEqual(self.put(3,"filled",103),"duplicate")
        with self.assertRaises(ValueError):self.put(2,"expired",104)
    def test_wrong_symbol(self):
        r=fixture_receipt(self.p,0,"open");r["symbol"]="XAUTUSD"
        self.assertEqual(self.l.observe(self.p,r,[],stamp=101)["state"],"unknown")
    def test_immutable(self):
        self.put(0,"open",101)
        with closing(self.l.connect()) as db, db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute("DELETE FROM observations")
    def test_four_market_direction_pairs(self):
        for s in ("BTCUSD","XAUTUSD"):
            for a in ("LONG","SHORT"):
                p=preview(s,a);l=LimitLedger(Path(self.tmp.name)/(s+a+".sqlite"))
                l.reserve(p,now=100,expires=150)
                r=l.observe(p,fixture_receipt(p,1,"expired"),fixture_protections(p,1),stamp=151)
                self.assertEqual(r["protection"],"fixture_bracket_matched")
                self.assertEqual(r["filled"],1)
                self.assertFalse(r["broker_verified"])
