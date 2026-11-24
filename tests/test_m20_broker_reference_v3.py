import unittest
from test_model_wire_v3 import raw,NOW
from tradebot.m20_broker_reference_v3 import project
class BrokerReferenceTests(unittest.TestCase):
 def fixture(self):
    return dict(raw("BTCUSD"),notional_type="vanilla",initial_margin_scaling_factor="0",maintenance_margin_scaling_factor="0",max_leverage_notional="100000",position_notional_limit="500000",default_leverage="10",maker_commission_rate="0.0002",taker_commission_rate="0.0005",position_size_limit=5000)
 def test_reference_only(self):
    r=project(self.fixture(),"BTCUSD",NOW)
    self.assertEqual(r["position_size_limit_raw"],5000)
    self.assertFalse(r["actual_order_margin_verified"])
    self.assertFalse(r["account_max_leverage_verified"])
    self.assertFalse(r["execution_authorized"])
 def test_invalid(self):
    for k,v in (("notional_type","inverse"),("initial_margin","NaN"),("position_size_limit",True),("default_leverage","0"),("maintenance_margin","10")):
        with self.assertRaises(ValueError):project(dict(self.fixture(),**{k:v}),"BTCUSD",NOW)
