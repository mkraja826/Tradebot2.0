import tempfile,unittest
from pathlib import Path
from recover_trading.liquidation_research import Journal,normalize,report,TOPIC
class LiquidationTests(unittest.TestCase):
    def packet(self):
        r={"T":100000,"s":"BTCUSDT","S":"Buy","v":"0.02","p":"60000"}
        return {"topic":TOPIC,"type":"snapshot","ts":100001,"data":[r,dict(r),{**r,"S":"Sell"}]}
    def test_position_side_and_duplicate_batch(self):
        p=self.packet();_,_,rows=normalize(p,100002)
        self.assertEqual([r["position_side"] for r in rows],["LONG","LONG","SHORT"])
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"liquidation.sqlite";j=Journal(path)
            i=j.start(100000);j.subscribed(i,100001)
            self.assertTrue(j.record(i,p,100002));self.assertFalse(j.record(i,p,100003))
            r=report(path,100004)
            self.assertEqual(r["status"],"heartbeat_observed")
            self.assertEqual(r["duplicate_batches"],1)
            self.assertEqual(sum(x["event_count"] for x in r["observed_events"]),3)
            j.end(i,100005,"disconnected")
            self.assertEqual(report(path,100006)["status"],"not_connected_or_unverified")
            j.db.close()
    def test_invalid_packets(self):
        for patch in ({"S":"unknown"},{"s":"ETHUSDT"},{"v":"NaN"},{"T":100002},{"p":"0"}):
            p=self.packet();p["data"][0].update(patch)
            with self.assertRaises(ValueError):normalize(p,100002)
        with self.assertRaises(ValueError):normalize(self.packet(),300000)
