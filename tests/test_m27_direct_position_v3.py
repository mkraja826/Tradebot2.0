import unittest
from datetime import datetime,timezone
from tradebot.m27_direct_position_v3 import project
NOW=1795525000
S="BTCUSD"
def account():
    return dict(symbol=S,subaccount="BTC",status="signed_read_only",signed_account_verified=True,wallet_receipt_verified=True,execution_authorized=False,observed_at=datetime.fromtimestamp(NOW,timezone.utc).isoformat(),positions=[],open_order_count=0,order_inventory_scope="account_wide_same_product")
class DirectInventoryTests(unittest.TestCase):
    def test_flat_and_orders(self):
        a=account()
        self.assertEqual(project(S,a,now=NOW)["status"],"flat_reported")
        a["open_order_count"]=1
        self.assertEqual(project(S,a,now=NOW)["status"],"flat_orders_present")
    def test_stale_wrong_identity(self):
        self.assertEqual(project(S,account(),now=NOW+61)["status"],"unknown")
        self.assertEqual(project("XAUTUSD",account(),now=NOW)["status"],"unknown")
    def test_protection_not_ownership(self):
        a=account();a["positions"]=[dict(symbol=S,protection=dict(status="signed_pending_bracket"))]
        a["open_order_count"]=2
        r=project(S,a,now=NOW)
        self.assertEqual(r["status"],"open_bracket_reported")
        self.assertFalse(r["protection_ownership_verified"])
        self.assertFalse(r["execution_authorized"])
        a["open_order_count"]=1
        self.assertEqual(project(S,a,now=NOW)["status"],"open_protection_unverified")
    def test_unverified(self):
        self.assertEqual(project(S,dict(account(),wallet_receipt_verified=False),now=NOW)["status"],"unknown")
        self.assertEqual(project(S,{},now=NOW)["status"],"unknown")
