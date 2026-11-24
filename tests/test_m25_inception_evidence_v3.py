import unittest
from unittest.mock import patch
from tradebot.m25_inception_evidence_v3 import funding_evidence

def row(i,v,**kw):
    return dict(id=str(i),amount=v,at_us=150,asset="USD",product_id=None,type="sub_account_transfer") | kw

class FundingTests(unittest.TestCase):
    def check(self,s,rows):
        with patch("tradebot.m25_inception_evidence_v3.normalize_posting",side_effect=lambda x:x):
            return funding_evidence(s,rows,100,200)
    def test_matches(self):
        for s,values,total in (("BTCUSD",["94.12","29.40","149.58"],"273.10"),("XAUTUSD",["100","5.88","70.59","100"],"276.47")):
            r=self.check(s,[row(i,v) for i,v in enumerate(values)])
            self.assertTrue(r["owner_amount_multiset_matches"])
            self.assertEqual(r["incoming_transfer_total_usd"],total)
            self.assertFalse(r["opening_equity_verified"])
    def test_duplicates(self):
        rows=[row(1,"94.12"),row(2,"29.40"),row(3,"149.58")]
        self.assertTrue(self.check("BTCUSD",rows+[rows[0]])["owner_amount_multiset_matches"])
    def test_wrong_amount_direction_or_currency(self):
        rows=[row(1,"94.12"),row(2,"29.40"),row(3,"149.58")]
        for extra in (row(4,"1"),row(4,"-1"),row(4,"1",asset="EUR")):
            self.assertFalse(self.check("BTCUSD",rows+[extra])["owner_amount_multiset_matches"])
    def test_outside_window(self):
        with self.assertRaises(ValueError):self.check("BTCUSD",[row(1,"94.12",at_us=99)])
    def test_conflicting_ids(self):
        with self.assertRaises(ValueError):self.check("BTCUSD",[row(1,"94.12"),row(1,"94.13")])
