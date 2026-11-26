import unittest
from recover_trading.liquidation_progress_v4 import breakeven,progress,excursion,POLICIES

def trade(s=1):
    return dict(id="0",first=0,last=180,sign=s,entry=100,sl=95 if s==1 else 105,
                tp=110 if s==1 else 90,rate=.00075,qty=.01)

class ProgressTests(unittest.TestCase):
    def test_break_even_both_directions(self):
        for s in (-1,1):
            t=trade(s);p=breakeven(t)*(1-s*.0002)
            self.assertAlmostEqual(s*(p-100)-t["rate"]*(100+p),0)

    def test_no_intrabar_activation_and_monotonic_stop(self):
        t=trade();bars={0:(100,106,99,100),60:(100,104,99,103),120:(103,104,101,103)}
        em={"1m":{0:(104,100,1),60:(104,100,1),120:(102,100,1)}}
        r=progress(t,bars,em,POLICIES["1m_halfR"])
        self.assertEqual(r["activation_bar"],120)
        self.assertEqual(r["final_sl"],101)
        self.assertEqual(r["adjustments"],1)

    def test_fee_stop_gap_not_guaranteed(self):
        t=trade();bars={0:(100,102,99,101),60:(99,100,98,99),120:(99,100,98,99)}
        r=progress(t,bars,{},POLICIES["fee_BE"])
        self.assertLess(r["net"]["2"],0)
        self.assertEqual(r["reason"],"progress_stop_crossed_at_update")
        self.assertEqual(excursion(t,bars,r)["post_exit_complete_bars"]["adverse_R"],.4)

    def test_short_one_R(self):
        t=trade(-1);bars={0:(100,101,94,94),60:(94,95,93,94),120:(94,95,93,94)}
        em={"1m":{0:(100,100,1),60:(95,100,1),120:(98,100,1)}}
        r=progress(t,bars,em,POLICIES["1m_oneR"])
        self.assertEqual(r["activation_bar"],60)
        self.assertEqual(r["final_sl"],96)
        self.assertEqual(r["adjustments"],1)

if __name__=="__main__":unittest.main()
