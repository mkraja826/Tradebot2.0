import tempfile,unittest
from pathlib import Path
from recover_trading.reference_positioning import normalize,save,report,TOPIC
class PositioningTests(unittest.TestCase):
    def fixture(self,t,oi="100"):
        return {"topic":TOPIC,"type":"snapshot","ts":t,"data":{"symbol":"BTCUSDT","openInterest":oi,"fundingRate":"-0.0001","markPrice":"60000","indexPrice":"60001","fundingIntervalHour":"8","nextFundingTime":str(t+3600000)}}
    def test_units_and_snapshot(self):
        p=self.fixture(1000000);r=normalize(p,1000001)
        self.assertEqual(r["indicative_funding_bps"],"-1.0000")
        self.assertEqual(r["indicative_funding_percent"],"-0.0100")
        p["type"]="delta"
        with self.assertRaises(ValueError):normalize(p,1000001)
    def test_change_and_staleness(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/"ref.sqlite"
            save(p,normalize(self.fixture(1000000),1000001))
            save(p,normalize(self.fixture(1300000,"95"),1300001))
            r=report(p,now=1300002)
            self.assertEqual(r["status"],"fresh_snapshot")
            self.assertEqual(r["oi_change_pct"]["5"]["value"],-5)
            self.assertEqual(report(p,now=1500000)["status"],"stale_snapshot")
            self.assertEqual(r["delta_funding_history_units"],"unverified")
