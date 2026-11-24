"""Adversarial fixture tests; not broker commissioning evidence."""
import unittest
from unittest.mock import patch
from copy import deepcopy
from tradebot.synthetic_lifecycle_v3 import project,fixture_receipt,fixture_protections
from test_m23_limit_lifecycle_v3 import preview

class ProtectionTests(unittest.TestCase):
    @patch("socket.socket",side_effect=AssertionError("offline only"))
    def test_both_sides_both_markets(self,network):
        for s in ("BTCUSD","XAUTUSD"):
            for side in ("LONG","SHORT"):
                p=preview(s,side);p["entry"]["kind"]="MARKET"
                for q,status in ((1,"open"),(3,"closed")):
                    r=project(p,fixture_receipt(p,q,status),fixture_protections(p,q))
                    self.assertEqual(r["protection_state"],"fixture_bracket_matched")
                    self.assertFalse(r["broker_verified"])
                    self.assertFalse(r["execution_authorized"])
        network.assert_not_called()
    def test_missing_and_wrong_protection(self):
        p=preview();r=fixture_receipt(p,1,"open");b=fixture_protections(p,1)
        for k,v in (("source","broker"),("parent_client_id","other"),("symbol","XAUTUSD"),("product_id",181689),("side","buy"),("reduce_only",False),("state","cancelled"),("contracts",3),("trigger","91"),("kind","take_profit"),("order_id",b[1]["order_id"])):
            x=deepcopy(b);x[0][k]=v
            with self.subTest(field=k):
                self.assertEqual(project(p,r,x)["protection_state"],"fixture_protection_unverified")
        for x in ([],b[:1],b+[b[0]],None):
            self.assertEqual(project(p,r,x)["protection_state"],"fixture_protection_unverified")
    def test_unknown_fill_not_protected(self):
        p=preview()
        r=project(p,None,fixture_protections(p,1))
        self.assertIsNone(r["filled_contracts"])
        self.assertEqual(r["protection_state"],"unknown")
        self.assertFalse(r["execution_authorized"])
    def test_rejected_entry_with_bracket(self):
        p=preview()
        r=project(p,fixture_receipt(p,0,"rejected"),fixture_protections(p,1))
        self.assertEqual(r["protection_state"],"unexpected_protection")

    def test_market_cancelled_partial_retains_protection(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from tradebot.synthetic_lifecycle_v3 import LifecycleLedger
        for s in ("BTCUSD","XAUTUSD"):
            for side in ("LONG","SHORT"):
                for terminal in ("cancelled","expired"):
                    p=preview(s,side);p["entry"]["kind"]="MARKET"
                    r=fixture_receipt(p,1,terminal)
                    with TemporaryDirectory() as d:
                        l=LifecycleLedger(Path(d)/"fixture.sqlite")
                        l.reserve(p)
                        l.observe(p,fixture_receipt(p,1,"open"),[],stamp=1)
                        x=l.observe(p,r,[],stamp=2)
                        self.assertEqual(x["filled_contracts"],1)
                        self.assertEqual(x["entry_state"],"fixture_"+terminal)
                        self.assertEqual(x["protection_state"],"fixture_protection_unverified")
                        x=l.observe(p,r,fixture_protections(p,1),stamp=3)
                        self.assertEqual(x["protection_state"],"fixture_bracket_matched")
                        self.assertFalse(x["execution_authorized"])
                        with self.assertRaisesRegex(ValueError,"terminal_entry_conflict"):
                            l.observe(p,fixture_receipt(p,1,"open"),[],stamp=4)
    def test_malformed_receipt_unknown(self):
        p=preview()
        for r in ([],True,"invalid"):
            self.assertIsNone(project(p,r,[])["filled_contracts"])
