import unittest
import json
from datetime import datetime, timezone, timedelta
from recover_trading.gold_v2_public_feeds import (cot,xaus,token,feature_packet,PublicFeeds)

NOW=datetime(2026,11,28,12,tzinfo=timezone.utc).timestamp()
STAMP=datetime.fromtimestamp(NOW-10,timezone.utc).isoformat()
class FeedTests(unittest.TestCase):
    def test_spot(self):
        raw={"source":"xaus.com","data_state":{"status":"fresh"},"stale":False,
             "price_as_of":STAMP,"spot_usd_oz":3000}
        self.assertEqual(xaus(json.dumps(raw),NOW)["price_usd_oz"],3000)
        raw["stale"]=True
        with self.assertRaises(ValueError):
            xaus(json.dumps(raw),NOW)
    def test_token_not_gold(self):
        raw=json.dumps([{"T":int((NOW-10)*1000),"p":"3001"}])
        self.assertEqual(token(raw,NOW,"PAXGUSDT")["price_usdt"],3001)
        with self.assertRaises(ValueError):
            token(raw,NOW+300,"PAXGUSDT")
    def test_cot(self):
        rows=[]
        for i in range(2):
            rows.append({"cftc_contract_market_code":"088691",
                         "report_date_as_yyyy_mm_dd":(datetime.fromtimestamp(NOW,timezone.utc).date()-timedelta(days=4+i*7)).isoformat(),
                         "open_interest_all":"200","m_money_positions_long_all":str(80-i*10),
                         "m_money_positions_short_all":"30"})
        result=cot(json.dumps(rows),NOW)
        self.assertEqual(result["managed_money_net_change"],10)
        rows[0]["cftc_contract_market_code"]="000000"
        with self.assertRaises(ValueError):
            cot(json.dumps(rows),NOW)
    def test_cache_failure(self):
        calls=[]
        def reader(url):
            calls.append(url)
            raise OSError()
        p=PublicFeeds(reader=reader,clock=lambda:NOW)
        first=p.collect()
        self.assertEqual(len(calls),6)
        self.assertTrue(all(i["status"]=="unavailable" for i in first.values()))
        p.collect()
        self.assertEqual(len(calls),6)
    def test_ratio_and_expiration(self):
        x={"xaus":{"status":"observed","observed_at":NOW-1,
                   "data":{"price_usd_oz":3000,"price_as_of":NOW-10}},
           "silver":{"status":"observed","observed_at":NOW-1,
                     "data":{"price_usd_oz":30,"price_as_of":NOW-10}}}
        self.assertEqual(feature_packet(x,NOW)["gold_silver_ratio"],100)
        self.assertIsNone(feature_packet(x,NOW+60)["gold_silver_ratio"])

    def test_slow_failure_retry(self):
        stamp=[NOW];calls=[]
        def reader(url):
            calls.append(url)
            raise TimeoutError()
        p=PublicFeeds(reader=reader,clock=lambda:stamp[0])
        p.collect();stamp[0]+=61;p.collect()
        self.assertEqual(len(calls),12)
