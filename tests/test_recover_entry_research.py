import unittest
from recover_trading.entry_research import entry_index,simulate,summarize

class EntryResearchTests(unittest.TestCase):
    def test_delay_and_original(self):
        rows=[{"open":100,"close":100},{"open":101,"close":102},{"open":102,"close":103},{"open":104,"close":999}]
        self.assertAlmostEqual(simulate(rows,"LONG","original",15)["net_bps"],385)
        self.assertAlmostEqual(simulate(rows,"SHORT","delay_10m",15)["net_bps"],-(104/102-1)*10000-15)
        self.assertIsNone(entry_index(rows[:2],"LONG","delay_5m"))
    def test_confirmation_completed_bar_only(self):
        rows=[{"open":100,"close":101},{"open":102,"close":99},{"open":103,"close":999}]
        self.assertEqual(entry_index(rows,"LONG","confirm_direction"),1)
        rows[1]["close"]=99999
        self.assertEqual(entry_index(rows,"LONG","confirm_direction"),1)
        self.assertIsNone(entry_index(rows,"SHORT","confirm_direction"))
    def test_pullback_reclaim(self):
        rows=[{"open":100,"close":99},{"open":99,"close":100},{"open":101,"close":100},{"open":102,"close":999}]
        self.assertEqual(entry_index(rows,"LONG","pullback_reclaim"),2)
        self.assertIsNone(entry_index(rows,"SHORT","pullback_reclaim"))
        self.assertIsNone(entry_index(rows[:3],"LONG","pullback_reclaim"))
    def test_untriggered_counts(self):
        rows=[{"open":100,"close":99},{"open":99,"close":98},{"open":98,"close":100}]
        miss=simulate(rows,"LONG","confirm_direction",15)
        self.assertFalse(miss["entered"])
        self.assertEqual(miss["net_bps"],0)
        r=summarize([miss,{"entered":True,"net_bps":20,"delay_s":300}])
        self.assertEqual(r["mean_net_bps_per_opportunity"],10)
        self.assertEqual(r["mean_net_bps_per_entry"],20)
