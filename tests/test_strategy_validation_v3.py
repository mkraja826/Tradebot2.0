import unittest
from collections import defaultdict,Counter
from tradebot.strategy_validation_v3 import overlap_update,overlap_report,replay
def r(id,status="triggered",directions=("LONG",),frame="5m"):
    return dict(id=id,status=status,directions=list(directions),frame=frame)
class ValidationTests(unittest.TestCase):
    def test_overlap_excludes_missing_and_other_frames(self):
        p=defaultdict(Counter)
        overlap_update(p,[r("B01"),r("B02"),r("B03",status="unavailable"),r("B04",frame="15m")])
        overlap_update(p,[r("B01"),r("B02",directions=("SHORT",))])
        overlap_update(p,[r("B01",status="no_signal",directions=()),r("B02")])
        overlap_update(p,[r("B01",status="no_signal",directions=()),r("B02",status="no_signal",directions=())])
        self.assertEqual(len(p),1)
        a=overlap_report(p)[0]
        self.assertEqual(a["joint_evaluable"],4)
        self.assertEqual(a["union"],3)
        self.assertEqual(a["both_active"],2)
        self.assertEqual(a["same_direction"],1)
        self.assertEqual(a["opposite_direction"],1)
        self.assertAlmostEqual(a["active_jaccard"],2/3)
        self.assertAlmostEqual(a["same_side_jaccard"],1/3)
    def test_invalid_window(self):
        for start,end in [(0,1),(300,0),(0,43500),(0,0),(False,300)]:
            with self.assertRaises(ValueError): replay("missing",start=start,end=end)
