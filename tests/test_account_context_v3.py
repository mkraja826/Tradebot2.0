import unittest
from datetime import datetime,timezone,timedelta
from tradebot.account_context_v3 import project
NOW=datetime(2026,11,24,6,tzinfo=timezone.utc)
def report():
    return {"environment":"delta-india-demo","mode":"read_only","source":"isolated_child_accounts","accounts":{"BTC":{
        "label":"BTC","symbol":"BTCUSD","status":"connected","margin_mode":"isolated_verified",
        "broker_checked_at":NOW.isoformat(),"net_equity":"100","positions":[],"live_position_count":0,"open_orders":0,"halted":True}}}
class AccountContextTests(unittest.TestCase):
    def test_partial_is_not_full_authority(self):
        a=project(report(),"BTCUSD",now=NOW)
        self.assertEqual(a["status"],"partial")
        self.assertTrue(a["signed_account_verified"])
        self.assertTrue(a["halted"])
        self.assertIsNone(a["available_margin_usd"])
    def test_stale_and_cross_account(self):
        self.assertEqual(project(report(),"BTCUSD",now=NOW+timedelta(seconds=61))["status"],"unavailable")
        self.assertEqual(project(report(),"XAUTUSD",now=NOW)["status"],"unavailable")
        r=report(); r["accounts"]["BTC"]["symbol"]="XAUTUSD"
        self.assertEqual(project(r,"BTCUSD",now=NOW)["status"],"unavailable")
    def test_wrong_exposure(self):
        r=report(); a=r["accounts"]["BTC"]; a.update(positions=[{"symbol":"XAUTUSD"}],live_position_count=1)
        self.assertEqual(project(r,"BTCUSD",now=NOW)["status"],"unavailable")
