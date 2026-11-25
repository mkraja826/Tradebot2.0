import unittest
from recover_trading.cost_sensitivity import sensitivity
class CostTests(unittest.TestCase):
    def test_costs_and_partition(self):
        r={"complete":True,"symbol":"BTCUSD","events":[
            {"partition":"development","rule_id":"B01","horizon_s":3600,"gross_bps":20},
            {"partition":"development","rule_id":"B01","horizon_s":3600,"gross_bps":0},
            {"partition":"holdout","rule_id":"B01","horizon_s":3600,"gross_bps":-50}]}
        a=sensitivity(r,costs=(0,10,15),minimum=2)
        x,y=a["rows"]
        self.assertEqual(x["break_even_round_trip_bps"],10)
        self.assertEqual(x["scenarios"][1]["mean_net_bps"],0)
        self.assertEqual(x["scenarios"][2]["win_rate"],.5)
        self.assertIsNone(y["break_even_round_trip_bps"])
        self.assertFalse(y["eligible"])
    def test_invalid(self):
        with self.assertRaises(ValueError):
            sensitivity({"complete":False})
