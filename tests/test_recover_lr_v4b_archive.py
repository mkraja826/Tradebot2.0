import unittest
import sqlite3
import tempfile
import json
from pathlib import Path
from recover_trading.lr_v4b import signals
from recover_trading.lr_v4b_archive import inspect


def fixture():
    candles=[{"time":i*60,"open":100,"high":101,"low":99,"close":100} for i in range(123)]
    candles[-1].update(open=99,high=101,low=97,close=100.8)
    event={"batch_id":"a","ordinal":0,"received_ms":122*60000+1000,"liquidated_position_side":"LONG","size_btc":1}
    return candles,event


class ArchiveTests(unittest.TestCase):
    def test_sweep_reclaim_and_deduplication(self):
        candles,event=fixture()
        result=signals(candles,[event,event],covered_through=7380)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]["side"],"buy")
        self.assertEqual(result[0]["signal_time"],7380)
        self.assertAlmostEqual(result[0]["initial_stop"],96.8)
        self.assertEqual(result[0]["liquidation_btc"],1)
    def test_no_signal_without_liquidation(self):
        candles,event=fixture()
        self.assertEqual(signals(candles,[],covered_through=7380),[])
    def test_archive_adapter(self):
        candles,event=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            m=Path(tmp)/"market.sqlite"
            e=Path(tmp)/"events.sqlite"
            with sqlite3.connect(m) as db:
                db.execute("CREATE TABLE samples(symbol,series,stamp,payload)")
                db.executemany("INSERT INTO samples VALUES(?,?,?,?)",[("BTCUSD","candle:1m",r["time"],json.dumps(r)) for r in candles])
            with sqlite3.connect(e) as db:
                db.execute("CREATE TABLE sessions(id,subscribed_ms,heartbeat_ms,ended_ms,status)")
                db.execute("INSERT INTO sessions VALUES(1,0,7380000,NULL,'subscribed')")
                db.execute("CREATE TABLE batches(id,session_id,received_ms)")
                db.execute("INSERT INTO batches VALUES('a',1,7321000)")
                db.execute("CREATE TABLE events(batch_id,ordinal,side,size)")
                db.execute("INSERT INTO events VALUES('a',0,'LONG','1')")
            r=inspect(m,e,now=7380)
            self.assertEqual(r["status"],"observed")
            self.assertEqual(r["recent_signal"]["side"],"buy")
            self.assertEqual(r["execution_effect"],"none")
            self.assertEqual(inspect(m,e,now=7500)["reason"],"heartbeat_stale_or_future")


if __name__=="__main__":
    unittest.main()
