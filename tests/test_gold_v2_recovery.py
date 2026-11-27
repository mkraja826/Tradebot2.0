import unittest
import tempfile
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import Mock
from recover_trading.broker import BrokerError
from recover_trading.engine import Journal
from recover_trading.gold_v2_episode import EpisodeJournal,client_id
from recover_trading.gold_v2_recovery import protective_receipts,local_no_submission,verify_no_submission,persist_no_submission

B=3600000
NOW=B+600
SEED={"symbol":"XAUTUSD","client_id":client_id(B),"signal_boundary":B,
      "flat_verified":True,"flat_observed_at":B+1,"product_id":42,"side":"buy","size":4}
def ts(t):return datetime.fromtimestamp(t,timezone.utc).isoformat()
def snapshot():
    return {"symbol":"XAUTUSD","observed":NOW,"positions":[],"active_orders":[],"active_orders_complete":True}
def fill():
    return {"created_at":ts(B+400),"order_id":10,"size":4}
def receipt():
    return {"id":10,"product_id":42,"side":"sell","reduce_only":True,"bracket_order":True,
            "stop_order_type":"stop_loss_order","stop_trigger_method":"mark_price","state":"closed",
            "size":4,"unfilled_size":0}
KNOWN={"10":{"kind":"stop_loss_order","first_seen":B+100}}
ERR=BrokerError(exchange_code="order_not_found")

class RecoveryTests(unittest.TestCase):
    def test_known_protective_leg(self):
        b=Mock();b._request.return_value=receipt()
        self.assertEqual(protective_receipts(b,SEED,[fill()],{"id":9},[],KNOWN),[receipt()])
        b._request.assert_called_once_with("GET","/v2/orders/10",auth=True)
    def test_unknown_leg_not_adopted(self):
        b=Mock()
        self.assertEqual(protective_receipts(b,SEED,[fill()],{"id":9},[],{}),[])
        b._request.assert_not_called()
    def test_wrong_trigger_rejected(self):
        b=Mock();b._request.return_value=dict(receipt(),stop_trigger_method="last_traded_price")
        self.assertEqual(protective_receipts(b,SEED,[fill()],{"id":9},[],KNOWN),[])
    def test_wrong_fill_quantity_rejected(self):
        b=Mock();b._request.return_value=receipt()
        self.assertEqual(protective_receipts(b,SEED,[dict(fill(),size=2)],{"id":9},[],KNOWN),[])
    def test_fill_precedes_observation(self):
        b=Mock()
        self.assertEqual(protective_receipts(b,SEED,[dict(fill(),created_at=ts(B+50))],{"id":9},[],KNOWN),[])
        b._request.assert_not_called()
    def test_recovery_requires_explicit_not_found(self):
        self.assertIsNone(verify_no_submission(SEED,[],snapshot(),now=NOW,complete=True,
            local_reason="no_local_order_reservation",error=BrokerError(category="timeout")))
    def test_ambiguous_order_not_released(self):
        self.assertIsNone(verify_no_submission(SEED,[],snapshot(),now=NOW,complete=True,
            local_reason=None,error=ERR))
    def test_fill_prevents_release(self):
        self.assertIsNone(verify_no_submission(SEED,[fill()],snapshot(),now=NOW,complete=True,
            local_reason="no_local_order_reservation",error=ERR))
    def test_incomplete_prevents_release(self):
        self.assertIsNone(verify_no_submission(SEED,[],snapshot(),now=NOW,complete=False,
            local_reason="no_local_order_reservation",error=ERR))
    def test_persistent_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            orders=Journal(Path(temp)/"orders.sqlite");ep=EpisodeJournal(Path(temp)/"episodes.sqlite")
            try:
                ep.reserve(SEED)
                reason=local_no_submission(orders,SEED)
                x=verify_no_submission(SEED,[],snapshot(),now=NOW,complete=True,local_reason=reason,error=ERR)
                self.assertEqual(x["status"],"terminal_no_submission")
                persist_no_submission(ep,SEED,x,now=NOW)
                with self.assertRaises(ValueError):persist_no_submission(ep,SEED,x,now=NOW+1)
            finally:orders.close();ep.close()
