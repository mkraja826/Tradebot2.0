import unittest,json
from datetime import datetime,timezone
from tradebot.gold_reference_v3 import parse,features
from tradebot.gold_strategies_v3 import RULES,evaluate
T=1800000000
def payload():
    return dict(symbol="XAU",currency="USD",price=100,updatedAt=datetime.fromtimestamp(T-10,timezone.utc).isoformat())
class GoldReferenceTests(unittest.TestCase):
    def test_fresh_reference_and_directions(self):
        r=parse(json.dumps(payload()),observed_us=T*1000000)
        self.assertFalse(r["exchange_trade_timestamp_verified"])
        t=dict(source="delta_demo_ticker",timestamp_us=(T-1)*1000000,bid=99.69,ask=99.71)
        f=features(dict(ticker=t,xau_reference=r),as_of=T)
        self.assertAlmostEqual(f["indicative_gold_basis_bps"],-30)
        rule=next(x for x in RULES if x.id=="G24")
        self.assertEqual(evaluate(rule,dict(f,close=100,p_close=99,ema9=99.5,rsi14=50))["directions"],["LONG"])
        t.update(bid=100.29,ask=100.31)
        self.assertEqual(evaluate(rule,dict(features(dict(ticker=t,xau_reference=r),as_of=T),close=100,p_close=101,ema9=100.5,rsi14=50))["directions"],["SHORT"])
        self.assertIsNone(features(dict(ticker=t,xau_reference=r),as_of=T+91)["indicative_gold_basis_bps"])
    def test_stale_wrong_currency_future_crossed(self):
        for p in (dict(payload(),currency="INR"),dict(payload(),price=-1),dict(payload(),updatedAt=datetime.fromtimestamp(T+1,timezone.utc).isoformat())):
            with self.assertRaises(ValueError): parse(json.dumps(p),observed_us=T*1000000)
        with self.assertRaises(ValueError): parse(json.dumps(payload()),observed_us=(T+61)*1000000)
        r=parse(json.dumps(payload()),observed_us=T*1000000)
        self.assertIsNone(features(dict(ticker=dict(source="delta_demo_ticker",timestamp_us=T*1000000,bid=101,ask=100),xau_reference=r),as_of=T)["indicative_gold_basis_bps"])
