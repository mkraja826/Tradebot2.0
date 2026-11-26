import unittest
from recover_trading.liquidation_prospective_v6 import START,END,N,enroll,summary,analyze
from recover_trading.liquidation_entry_v3 import RESERVATION_S,SOURCE

def obs(t):
    return (t*1000,dict(source=SOURCE,status="observed_research_only",as_of_ms=t*1000,
      features=dict(price_move_bps=-25,oi_change_pct=-.2,observed_sizes_btc={"LONG":"2"},observed_counts={"LONG":3})))

class ProspectiveTests(unittest.TestCase):
    def test_excludes_past_and_overlaps_and_immature(self):
        rows=[obs(START-1),obs(START),obs(START+60),obs(START+RESERVATION_S)]
        self.assertEqual([r[0] for r in enroll(rows,START+RESERVATION_S)],[START*1000])
        self.assertEqual(len(enroll(rows,START+2*RESERVATION_S)),2)

    def test_first_100_and_fixed_end(self):
        rows=[obs(START+i*RESERVATION_S) for i in range(N+10)]
        slots=enroll(rows,END+RESERVATION_S)
        self.assertEqual(len(slots),N)
        self.assertEqual(slots[-1][0],(START+(N-1)*RESERVATION_S)*1000)
        self.assertEqual(enroll([obs(END)],END+RESERVATION_S),[])

    def test_unknown_not_replaced(self):
        out=analyze([obs(START)],{},{"1m":{},"3m":{},"15m":{}},START+RESERVATION_S)
        self.assertEqual(out["enrolled"],1)
        self.assertEqual(out["groups"]["all"]["all_available"]["retest_fixed"]["states"],{"unknown":1})
        self.assertEqual(out["groups"]["all"]["common_known_count"],0)

if __name__=="__main__":unittest.main()
