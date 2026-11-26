import unittest
from recover_trading.liquidation_structure_v5 import context,classify,summarize

def data():
    t=7200
    minute={i:(100,101,99,100,1) for i in range(t-3600,t,60)}
    minute[t-600]=(100,110,99,100,1)
    maps={"1m":{t:(100,100,1)},"15m":{t:(99,98,1)}}
    return t,minute,maps

class ConfluenceTests(unittest.TestCase):
    def test_context_no_future_open_or_candle(self):
        t,m,a=data();before=context(t,1,m,a)
        m[t]=(900,1000,800,900,1)
        self.assertEqual(context(t,1,m,a),before)
        self.assertTrue(before["trend"])
        self.assertTrue(before["room"])
        self.assertTrue(before["fees"])
        self.assertEqual(before["nearest_obstacle"],110)

    def test_unknown_not_infinite_room(self):
        t,m,a=data();m[t-600]=(100,101,99,100,1)
        x=context(t,1,m,a)
        self.assertIsNone(x["room"])
        self.assertEqual(classify(x,("room",))[0],"unknown")
        self.assertEqual(classify({"trend":False,"room":None},("trend","room"))[0],"no_trade")

    def test_short_alignment_and_room(self):
        t,m,a=data();m[t-600]=(100,101,90,100,1)
        a["15m"][t]=(101,102,1)
        x=context(t,-1,m,a)
        self.assertTrue(x["trend"])
        self.assertTrue(x["room"])
        self.assertEqual(x["nearest_obstacle"],90)

    def test_missing_is_not_zero_return(self):
        e=[{"policies":{"p":{"status":"unknown"}}},{"policies":{"p":{"status":"no_trade"}}}]
        out=summarize(e,"p")
        self.assertEqual(out["unknown"],1)
        self.assertEqual(out["costs"]["2"]["known_opportunity_metrics_bps"]["breakeven"],1)

if __name__=="__main__":unittest.main()
