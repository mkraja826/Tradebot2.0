"""Regression coverage for evidence-backed, BTC-only candle quarantine recovery."""
from contextlib import closing
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs,urlsplit
import json
import sqlite3
import unittest

from tradebot.btc_quarantine_recovery import STAMPS,corroborate,recover,HOSTS


class BrokerSources:
    def __init__(self, *, disagree=False, missing_minute=False):
        self.disagree=disagree
        self.missing_minute=missing_minute
        self.calls=[]

    def __call__(self, request, timeout):
        url=request.full_url
        parsed=urlsplit(url)
        p=parse_qs(parsed.query)
        host=parsed.scheme+"://"+parsed.netloc
        resolution=p["resolution"][0]
        self.calls.append((host,resolution))
        rows=[]
        for t in STAMPS:
            if resolution=="5m":
                rows.append(dict(time=t,open=100,high=102,low=99,
                                 close=101,volume=10))
            else:
                for i in range(5):
                    if self.missing_minute and i==2 and t==STAMPS[0]:
                        continue
                    rows.append(dict(time=t+i*60,open=100,high=102,
                                     low=99,close=101,volume=2))
        if self.disagree and host==HOSTS[1] and resolution=="5m":
            rows[0]["close"]=100
        return BytesIO(json.dumps({"success":True,"result":rows}).encode())


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/"delta-demo-candles.sqlite"
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("""CREATE TABLE candles(symbol TEXT,t INTEGER,
                o REAL,h REAL,l REAL,c REAL,v REAL,PRIMARY KEY(symbol,t))""")
            db.execute("""CREATE TABLE candle_quarantine(symbol TEXT,t INTEGER,
                o REAL,h REAL,l REAL,c REAL,v REAL,reason TEXT,
                PRIMARY KEY(symbol,t))""")
            for t in STAMPS:
                db.execute("INSERT INTO candle_quarantine VALUES(?,?,?,?,?,?,?,?)",
                           ("BTCUSD",t,97,98,96,97,1,
                            "conflicting_historical_refetch"))
                for distance in (300,600,900):
                    for neighbor in (t-distance,t+distance):
                        if neighbor in STAMPS:
                            continue
                        db.execute("INSERT OR IGNORE INTO candles VALUES(?,?,?,?,?,?,?)",
                                   ("BTCUSD",neighbor,100,102,99,101,8))
            db.execute("INSERT INTO candles VALUES(?,?,?,?,?,?,?)",
                       ("XAUTUSD",STAMPS[0],3600,3602,3599,3601,10))
            db.commit()

    def counts(self):
        with closing(sqlite3.connect(self.path)) as db:
            qu=db.execute("SELECT COUNT(*) FROM candle_quarantine").fetchone()[0]
            active=db.execute("SELECT COUNT(*) FROM candles WHERE symbol='BTCUSD' "
                              "AND t IN (?,?)",STAMPS).fetchone()[0]
            check=db.execute("SELECT name FROM sqlite_master WHERE "
                             "name='candle_recovery_audit'").fetchone()
            return qu,active,bool(check)

    def test_public_corroboration_requires_all_four_gets(self):
        f=BrokerSources()
        got,hashes=corroborate(STAMPS,opener=f)
        self.assertEqual(len(f.calls),4)
        self.assertEqual(len(hashes),4)
        self.assertEqual(got[STAMPS[0]][5],Decimal(10))
        self.assertEqual(got[STAMPS[1]][4],Decimal(101))

    def test_read_only_default_does_not_mutate_database(self):
        out=recover(self.path,STAMPS,opener=BrokerSources())
        self.assertFalse(out["applied"])
        self.assertEqual(self.counts(),(2,0,False))

    def test_atomic_repair_keeps_original_quarantine_in_audit(self):
        out=recover(self.path,STAMPS,apply=True,opener=BrokerSources())
        self.assertTrue(out["applied"])
        self.assertEqual(self.counts(),(0,2,True))
        with closing(sqlite3.connect(self.path)) as db:
            audit=db.execute("SELECT t,original_json,replacement_json,"
                             "source_sha256_json FROM candle_recovery_audit "
                             "ORDER BY t").fetchall()
            self.assertEqual([a[0] for a in audit],list(STAMPS))
            for _,old,new,hashes in audit:
                self.assertEqual(json.loads(old)["open"],97)
                self.assertEqual(json.loads(old)["reason"],
                                 "conflicting_historical_refetch")
                self.assertEqual(json.loads(new)["open"],"100")
                self.assertEqual(len(json.loads(hashes)),2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM candles "
                        "WHERE symbol='XAUTUSD'").fetchone()[0],1)
            with self.assertRaisesRegex(sqlite3.IntegrityError,"immutable"):
                db.execute("DELETE FROM candle_recovery_audit")
            with self.assertRaisesRegex(sqlite3.IntegrityError,"immutable"):
                db.execute("UPDATE candle_recovery_audit SET policy='fake'")

    def test_second_repair_does_not_overwrite_provenance(self):
        recover(self.path,STAMPS,apply=True,opener=BrokerSources())
        with self.assertRaises(ValueError):
            recover(self.path,STAMPS,apply=True,opener=BrokerSources())
        self.assertEqual(self.counts(),(0,2,True))

    def test_cross_source_disagreement_blocks_any_db_change(self):
        with self.assertRaisesRegex(ValueError,"disagree"):
            recover(self.path,STAMPS,apply=True,opener=BrokerSources(disagree=True))
        self.assertEqual(self.counts(),(2,0,False))

    def test_missing_one_minute_blocks_any_db_change(self):
        with self.assertRaisesRegex(ValueError,"one-minute"):
            recover(self.path,STAMPS,apply=True,
                    opener=BrokerSources(missing_minute=True))
        self.assertEqual(self.counts(),(2,0,False))

    def test_unknown_quarantine_reason_not_repaired(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE candle_quarantine SET reason='extreme_neighbor_dislocation'")
            db.commit()
        with self.assertRaisesRegex(ValueError,"conflict"):
            recover(self.path,STAMPS,apply=True,opener=BrokerSources())
        self.assertEqual(self.counts(),(2,0,False))

    def test_source_failures_dont_create_audit(self):
        def failed(request,timeout):
            raise OSError("broker API unavailable")
        with self.assertRaises(OSError):
            recover(self.path,STAMPS,apply=True,opener=failed)
        self.assertEqual(self.counts(),(2,0,False))

    def test_no_invalid_repair_target(self):
        with self.assertRaises(ValueError):
            corroborate([STAMPS[0],STAMPS[0]],opener=BrokerSources())
        with self.assertRaises(ValueError):
            corroborate([STAMPS[0]+30],opener=BrokerSources())


if __name__=="__main__":
    unittest.main()

