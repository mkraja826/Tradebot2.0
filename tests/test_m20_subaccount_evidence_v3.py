import unittest
from tradebot.m20_subaccount_evidence_v3 import classify
from unittest.mock import patch
class EvidenceTests(unittest.TestCase):
 @patch("tradebot.m20_subaccount_evidence_v3.normalize_posting",side_effect=lambda x:x)
 def test_types(self,m):
    def p(i,k,asset="USD",pid=None):
        return dict(id=i,at_us=2,asset=asset,product_id=pid,type=k)
    self.assertEqual(classify([p("1","sub_account_transfer"),p("2","funding"),p("3","conversion"),p("4","cashflow",pid="999")],1,3,84),dict(transfers=1,capital=0,trading=1,unclassified=2))
 @patch("tradebot.m20_subaccount_evidence_v3.normalize_posting",side_effect=lambda x:x)
 def test_window(self,m):
    with self.assertRaises(ValueError):
        classify([dict(id="a",at_us=4)],1,3,84)
