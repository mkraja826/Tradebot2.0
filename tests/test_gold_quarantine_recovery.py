"""Gold-only conflict recovery tests; never use mixed-account ledger."""
from contextlib import closing
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlsplit
import json
import sqlite3
import unittest

from tradebot.gold_quarantine_recovery import STAMPS, HOSTS, corroborate, recover


class FakeDeltaGold:
    def __init__(self, *, mismatch=False, missing_minute=False, malformed=False):
        self.calls=[]
        self.mismatch=mismatch
        self.missing_minute=missing_minute
        self.malformed=malformed

    def __call__(self, req, timeout):
        url=urlsplit(req.full_url)
        host=url.scheme+"://"+url.netloc
        q=parse_qs(url.query)
        self.calls.append((host,q["resolution"][0],q["symbol"][0]))
        t=STAMPS[0]
        if q["resolution"][0]=="5m":
            rows=[dict(time=t,open=100,high=102,low=99,close=101,volume=10)]
            if host==HOSTS[1] and self.mismatch: rows[0]["close"]=100
        else:
            rows=[dict(time=t+i*60,open=100,high=102,low=99,
                       close=101,volume=2) for i in range(5)
                  if not (self.missing_minute and i==2)]
        if self.malformed:rows[0]["open"]=-1
        return BytesIO(json.dumps({"result":rows}).encode())


class GoldRecoveryTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/"delta-demo-candles.sqlite"
        t=STAMPS[0]
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("""CREATE TABLE candles(
                symbol TEXT, t INTEGER, o REAL, h REAL, l REAL, c REAL,
                v REAL, PRIMARY KEY(symbol,t))""")
            db.execute("""CREATE TABLE candle_quarantine(
                symbol TEXT,t INTEGER,o REAL,h REAL,l REAL,c REAL,v REAL,
                reason TEXT, PRIMARY KEY(symbol,t))""")
            db.execute("INSERT INTO candle_quarantine VALUES(?,?,?,?,?,?,?,?)",
                       ("XAUTUSD",t,90,92,88,91,1,"conflicting_historical_refetch"))
            for offset in (-900,-600,-300,300,600,900):
                db.execute("INSERT INTO candles VALUES(?,?,?,?,?,?,?)",
                           ("XAUTUSD",t+offset,100,102,99,101,8))
            db.execute("INSERT INTO candles VALUES(?,?,?,?,?,?,?)",
                       ("BTCUSD",t,60000,60200,59900,60100,10))
            db.commit()

    def state(self):
        with closing(sqlite3.connect(self.path)) as db:
            return (
                db.execute("SELECT count(*) FROM candle_quarantine "
                           "WHERE symbol='XAUTUSD'").fetchone()[0],
                db.execute("SELECT count(*) FROM candles WHERE symbol='XAUTUSD' "
                           "AND t=?",(STAMPS[0],)).fetchone()[0],
                db.execute("SELECT c FROM candles WHERE symbol='BTCUSD' "
                           "AND t=?",(STAMPS[0],)).fetchone()[0],
                bool(db.execute("SELECT name FROM sqlite_master WHERE "
                                "name='candle_recovery_audit'").fetchone()))

    def test_only_public_gold_perp_four_requests_and_consensus(self):
        fake=FakeDeltaGold()
        value, hashes=corroborate(STAMPS,opener=fake)
        self.assertEqual(len(fake.calls),4)
        self.assertEqual({x[2] for x in fake.calls},{"XAUTUSD"})
        self.assertEqual(set(x[:2] for x in fake.calls),
                         {(h,r) for h in HOSTS for r in ("1m","5m")})
        self.assertEqual(value[STAMPS[0]][5],Decimal(10))
        self.assertEqual(len(hashes),2)

    def test_dry_run_is_immutable(self):
        result=recover(self.path,opener=FakeDeltaGold())
        self.assertFalse(result["applied"])
        self.assertEqual(self.state(),(1,0,60100.0,False))

    def test_recovered_gold_cannot_touch_btc_and_preserves_audit(self):
        result=recover(self.path,apply=True,opener=FakeDeltaGold())
        self.assertTrue(result["applied"])
        self.assertEqual(self.state(),(0,1,60100.0,True))
        with closing(sqlite3.connect(self.path)) as db:
            evidence=db.execute("SELECT original_json,replacement_json,"
                                "source_sha256_json FROM candle_recovery_audit "
                                "WHERE symbol='XAUTUSD' AND t=?",STAMPS).fetchone()
            self.assertEqual(json.loads(evidence[0])["open"],90)
            self.assertEqual(json.loads(evidence[1])["open"],"100")
            self.assertEqual(len(json.loads(evidence[2])),2)
            self.assertEqual(db.execute("SELECT count(*) FROM candle_recovery_audit "
                                        "WHERE symbol='BTCUSD'").fetchone()[0],0)
            with self.assertRaisesRegex(sqlite3.IntegrityError,"immutable"):
                db.execute("DELETE FROM candle_recovery_audit")
            with self.assertRaisesRegex(sqlite3.IntegrityError,"immutable"):
                db.execute("UPDATE candle_recovery_audit SET policy='bad'")

    def test_replay_is_refused(self):
        recover(self.path,apply=True,opener=FakeDeltaGold())
        with self.assertRaises(ValueError):
            recover(self.path,apply=True,opener=FakeDeltaGold())
        self.assertEqual(self.state(),(0,1,60100.0,True))

    def test_public_host_disagreement_fails_closed(self):
        with self.assertRaisesRegex(ValueError,"disagree"):
            recover(self.path,apply=True,opener=FakeDeltaGold(mismatch=True))
        self.assertEqual(self.state(),(1,0,60100.0,False))

    def test_missing_one_minute_fails_closed(self):
        with self.assertRaisesRegex(ValueError,"one-minute"):
            recover(self.path,apply=True,opener=FakeDeltaGold(missing_minute=True))
        self.assertEqual(self.state(),(1,0,60100.0,False))

    def test_malformed_public_candle_fails_closed(self):
        with self.assertRaises(ValueError):
            recover(self.path,apply=True,opener=FakeDeltaGold(malformed=True))
        self.assertEqual(self.state(),(1,0,60100.0,False))

    def test_wrong_quarantine_reason_fails_closed(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE candle_quarantine SET reason='price_anomaly'")
            db.commit()
        with self.assertRaisesRegex(ValueError,"conflict"):
            recover(self.path,apply=True,opener=FakeDeltaGold())
        self.assertEqual(self.state(),(1,0,60100.0,False))

    def test_public_api_failure_never_mutates(self):
        def unavailable(req, timeout):
            raise OSError("public API down")
        with self.assertRaises(OSError):
            recover(self.path,apply=True,opener=unavailable)
        self.assertEqual(self.state(),(1,0,60100.0,False))

    def test_untrusted_symbol_and_unaligned_target_refused(self):
        with self.assertRaises(ValueError):
            corroborate((STAMPS[0]+1,),opener=FakeDeltaGold())
        with self.assertRaises(ValueError):
            corroborate((STAMPS[0], STAMPS[0]),opener=FakeDeltaGold())

