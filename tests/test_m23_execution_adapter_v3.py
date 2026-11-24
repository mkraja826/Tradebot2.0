import unittest
from unittest.mock import patch
from tradebot.m23_execution_adapter_v3 import exercise,adapt
from tradebot.opportunity_journal_v3 import digest

NOW=1795519800
def spec(s):
    return dict(symbol=s,product_id=84 if s=="BTCUSD" else 181689,contract_value="0.001",tick_size="0.1" if s=="BTCUSD" else "0.01",source="delta_demo_public_product",observed_at=NOW)

class AdapterTests(unittest.TestCase):
    def test_both_markets(self):
        for s in ("BTCUSD","XAUTUSD"):
            r=exercise(s,spec(s),NOW)
            self.assertEqual(r,dict(WAIT_MARKET="wait_no_order",LONG_MARKET="existing_validator_passed_fixture",SHORT_MARKET="existing_validator_passed_fixture",LONG_LIMIT="limit_execution_not_supported",SHORT_LIMIT="limit_execution_not_supported"))
    def test_nonfixture_rejected(self):
        p=dict(symbol="BTCUSD",account={"mode":"signed_read_only"},product=spec("BTCUSD"))
        q=dict(payload=p,model_if_enabled="GPT-6.1 Sol",request_sha256=digest(p))
        with self.assertRaises(ValueError):adapt(q,{},spec("BTCUSD"),{},{},now=NOW)
    def test_cross_market_quote_rejected(self):
        p=dict(symbol="BTCUSD",account={"mode":"synthetic_fixture"},product=spec("BTCUSD"))
        q=dict(payload=p,model_if_enabled="GPT-6.1 Sol",request_sha256=digest(p))
        with self.assertRaises(ValueError):adapt(q,{},spec("BTCUSD"),dict(symbol="XAUTUSD",mode="synthetic_fixture",observed_at=NOW),{},now=NOW)
    @patch("tradebot.m23_execution_adapter_v3.assess_fire_plan")
    def test_risk_rejection_propagates(self,gate):
        gate.side_effect=ValueError("existing risk gate")
        with self.assertRaisesRegex(ValueError,"existing risk gate"):exercise("BTCUSD",spec("BTCUSD"),NOW)
