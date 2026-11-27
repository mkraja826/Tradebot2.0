import unittest
from datetime import datetime,timezone,timedelta
from recover_trading.gold_v2_fundamentals import context

NOW=datetime(2026,11,28,12,tzinfo=timezone.utc).timestamp()

def series(start,end):
    day=datetime.fromtimestamp(NOW,timezone.utc).date()
    return [{"date":(day-timedelta(days=6-i)).isoformat(),
             "value":start+(end-start)*i/5} for i in range(6)]

def item(data):
    return {"status":"ready","observed_at":NOW-1,"source":"fred_as_observed",
            "macro_history":{"source":"fred_daily_as_observed","series":data}}

def refs():
    return {"broad_dollar":item({"DTWEXBGS":series(120,119)}),
            "yields":item({"DGS10":series(4,3.9),"DFII10":series(2,1.9)})}

class FundamentalTests(unittest.TestCase):
    def test_supportive(self):
        x=context(refs(),{},as_of=NOW)
        self.assertEqual(x["macro_bias_hypothesis"],"gold_supportive")
        self.assertAlmostEqual(x["macro"]["real_yield_5obs_bp"],-10)
    def test_unknown(self):
        self.assertEqual(context({}, {},as_of=NOW)["macro_bias_hypothesis"],"unknown")
    def test_future_observation(self):
        r=refs()
        r["yields"]["observed_at"]=NOW+1
        self.assertIsNone(context(r,{},as_of=NOW)["macro"]["real_yield_5obs_bp"])
    def test_stale_observation(self):
        r=refs()
        r["yields"]["observed_at"]=NOW-30000
        self.assertEqual(context(r,{},as_of=NOW)["macro_bias_hypothesis"],"unknown")
    def test_reference_timestamp(self):
        spot={"source":"gold_api_indicative_spot","symbol":"XAU","currency":"USD",
              "timestamp_us":int((NOW-5)*1e6),"provider_updated_us":int((NOW-10)*1e6),
              "price_usd_per_troy_ounce":3000}
        x=context({},spot,as_of=NOW,delta_close=3003,delta_closed_at=NOW-15)
        self.assertAlmostEqual(x["spot_reference"]["basis_bps"],10)
        self.assertIsNone(context({},spot,as_of=NOW,delta_close=3003,
                                  delta_closed_at=NOW-120)["spot_reference"]["basis_bps"])
    def test_fomc(self):
        stamp=datetime.fromtimestamp(NOW-60,timezone.utc).isoformat()
        r={"fomc_release":{"status":"ready","observed_at":NOW-1,
           "data":{"source":"federal_reserve_monetary_rss","published_at":stamp}}}
        self.assertTrue(context(r,{},as_of=NOW)["events"]["fomc_release"]["recent_45m"])
    def test_future_event(self):
        stamp=datetime.fromtimestamp(NOW+60,timezone.utc).isoformat()
        r={"fomc_release":{"status":"ready","observed_at":NOW-1,
           "data":{"source":"federal_reserve_monetary_rss","published_at":stamp}}}
        self.assertEqual(context(r,{},as_of=NOW)["events"]["fomc_release"]["status"],"unavailable")
