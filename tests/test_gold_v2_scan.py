import unittest
from recover_trading.gold_v2_scan import scan, FRAME_MAP

NOW=3600*1000

def feed(client,symbol,*,as_of,frames,count):
    assert symbol=="XAUTUSD"
    result={}
    for frame in frames:
        seconds=FRAME_MAP[frame]
        end=as_of//seconds*seconds
        result[frame]={"status":"ready","bars":[
            {"time":end-(count-i)*seconds,"open":3000+i*.1,
             "high":3001+i*.1,"low":2999+i*.1,"close":3000+i*.1,
             "volume":1.0} for i in range(count)]}
    return {"symbol":symbol,"as_of":as_of,"frames":result}

class ScanTests(unittest.TestCase):
    def test_open_to_close_timestamp(self):
        result=scan(None,NOW,collector=feed)
        self.assertEqual(result["status"],"observed")
        self.assertEqual(result["execution_effect"],"none")
    def test_wrong_symbol(self):
        def wrong(*a,**kw):
            return dict(feed(*a,**kw),symbol="BTCUSD")
        with self.assertRaises(ValueError):
            scan(None,NOW,collector=wrong)
    def test_unavailable_frame(self):
        def missing(*a,**kw):
            x=feed(*a,**kw)
            x["frames"]["1h"]={"status":"unavailable"}
            return x
        self.assertEqual(scan(None,NOW,collector=missing)["status"],"data_unusable")
