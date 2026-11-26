import unittest
from recover_trading.lr_v4b import bracket, signals, trail


class LRv4bTests(unittest.TestCase):
    def test_brackets(self):
        self.assertEqual(bracket("buy", 100, 90)["target"], 120)
        self.assertEqual(bracket("sell", 100, 110)["target"], 80)
        with self.assertRaises(ValueError):
            bracket("buy", 100, 110)

    def test_activation_is_r_not_price_units(self):
        self.assertFalse(trail("buy",100,90,90,{"high":104,"low":98,"close":103},102)["activated"])
        result=trail("buy",100,90,90,{"high":105,"low":98,"close":104},103)
        self.assertTrue(result["activated"])
        self.assertEqual(result["proposed_stop"],103)

    def test_stop_never_retreats(self):
        self.assertEqual(trail("buy",100,90,104,{"high":107,"low":103,"close":105},102,True)["proposed_stop"],104)
        self.assertEqual(trail("sell",100,110,96,{"high":98,"low":93,"close":95},99,True)["proposed_stop"],96)

    def test_short_activation(self):
        self.assertFalse(trail("sell",100,110,110,{"high":101,"low":96,"close":97},98)["activated"])
        self.assertTrue(trail("sell",100,110,110,{"high":101,"low":95,"close":97},98)["activated"])

    def test_empty_history(self):
        self.assertEqual(signals([], [], covered_through=0),[])

    def test_coverage_and_candle_gaps(self):
        c={"time":0,"open":100,"high":101,"low":99,"close":100}
        with self.assertRaises(ValueError):
            signals([c], [], covered_through=59)
        with self.assertRaises(ValueError):
            signals([c,{**c,"time":120}], [], covered_through=180)


if __name__ == "__main__":
    unittest.main()
