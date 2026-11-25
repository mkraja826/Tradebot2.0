import tempfile,sqlite3,json,unittest
from pathlib import Path
from recover_trading.dual_market import compare,run,COUNT
class DualMarketTests(unittest.TestCase):
    def bars(self,end,step,reverse=False):
        return [{"time":t,"open":p,"close":p,"high":p+1,"low":p-1,"volume":10} for i,t in enumerate(range(end-COUNT*step,end,step)) for p in [100+(COUNT-i if reverse else i)/10]]
    def test_same_windows_and_direction_difference(self):
        end=1800000000;demo=self.bars(end,300);ref=self.bars(end,300,True)
        same=compare("BTCUSD","5m",end,demo,demo)
        self.assertEqual(same["agreement_count"],same["comparable_count"])
        self.assertEqual(same["signed_close_difference_bps"],0)
        diff=compare("BTCUSD","5m",end,demo,ref)
        self.assertFalse(diff["directional_checks"]["ema50_vs_200"]["agree"])
        with self.assertRaises(ValueError):compare("BTCUSD","5m",end,demo,ref[:-1])
    def test_missing_and_stale_frames_separate(self):
        end=1800000000
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"BTCUSD";p.mkdir()
            with sqlite3.connect(p/"market.sqlite") as db:
                db.execute("CREATE TABLE samples(symbol TEXT,series TEXT,stamp INTEGER,payload TEXT)")
                db.executemany("INSERT INTO samples VALUES('BTCUSD','candle:5m',?,?)",[(b["time"],json.dumps(b)) for b in self.bars(end,300)])
            def fetch(symbol,frame,cutoff,count):
                self.assertEqual(cutoff,end);return self.bars(end,300)
            r=run(d,"BTCUSD",end+300,fetch)
            self.assertEqual(r["frames"]["5m"]["lag_s"],300)
            self.assertEqual(r["frames"]["15m"]["status"],"demo_unavailable")
            self.assertEqual(r["execution_effect"],"none")
            self.assertTrue((p/"dual_market.json").exists())
