import sqlite3
import unittest
import json
from contextlib import closing
from recover_trading.lr_v4b_attribution import Attribution,management_proposal


class OwnershipTests(unittest.TestCase):
    def test_reserve_and_match_exact_receipt(self):
        with closing(sqlite3.connect(":memory:")) as db:
            db.execute("CREATE TABLE orders(client_id,symbol,status,detail)")
            j=Attribution(db)
            s={"version":"lr-v4b","symbol":"BTCUSD","signal_time":600,"burst_time":540,"side":"buy","initial_stop":90}
            claim=j.reserve(s,601)
            self.assertIsNone(j.reserve(s,602))
            with self.assertRaises(ValueError):
                j.reserve(s,660)
            pos={"size":2,"entry_price":100,"created_at":"fixture","product_id":1}
            line={"entry_order":"9","size":"2","entry_price":"100"}
            self.assertIsNone(j.ownership(line,pos))
            db.execute("INSERT INTO orders VALUES(?,?,?,?)",(claim["client_id"],"BTCUSD","acknowledged",json.dumps({"id":9,"client_order_id":claim["client_id"],"product_id":1})))
            owner=j.ownership(line,pos)
            self.assertEqual(owner["target"],120)
            self.assertIsNone(j.ownership(line,{**pos,"size":3}))
            self.assertIsNone(j.ownership({**line,"entry_order":"10"},pos))
    def test_post_fill_activation_and_timeout(self):
        owner={"side":"buy","entry":100,"initial_stop":90,"target":120}
        rows=[{"time":60,"high":120,"low":99,"close":110},{"time":120,"high":104,"low":98,"close":103}]
        r=management_proposal(owner,90,rows,[105,102],fill_time=90,now=180)
        self.assertFalse(r["activated"])
        rows[-1]["high"]=105
        r=management_proposal(owner,90,rows,[105,102],fill_time=90,now=180)
        self.assertEqual(r["stop"],102)
        self.assertTrue(r["activated"])
        self.assertEqual(management_proposal(owner,90,[],[],fill_time=90,now=3690)["action"],"close_at_timeout")
        with self.assertRaises(ValueError):
            management_proposal(owner,90,[],[],fill_time=90,now=180)
