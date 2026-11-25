import unittest
from recover_trading.chart_studies import studies
class ChartStudyTests(unittest.TestCase):
    def rows(self,n,start=0,step=60,constant=False):
        return [{"time":start+i*step,"open":100+i*(not constant),"high":101+i*(not constant),"low":99+i*(not constant),"close":100+i*(not constant),"volume":2} for i in range(n)]
    def test_warmups_and_rising_series(self):
        r=studies(self.rows(201),60)
        self.assertIsNone(r[7]["ema9"]);self.assertEqual(r[8]["ema9"],104)
        self.assertIsNone(r[198]["ema200"]);self.assertIsNotNone(r[199]["ema200"])
        self.assertIsNone(r[13]["rsi"]);self.assertEqual(r[14]["rsi"],100)
        self.assertAlmostEqual(r[33]["macd"],7);self.assertAlmostEqual(r[33]["macd_hist"],0)
        self.assertEqual(r[19]["bb_mid"],109.5);self.assertEqual(r[20]["support"],99);self.assertEqual(r[20]["resistance"],120)
        self.assertEqual(r[13]["atr"],2);self.assertAlmostEqual(r[20]["vwap"],110)
    def test_gap_reset(self):
        r=studies(self.rows(25)+self.rows(15,start=1800),60)
        self.assertIsNone(r[25]["ema9"]);self.assertIsNone(r[25]["support"]);self.assertIsNone(r[25]["vwap"]);self.assertEqual(r[39]["rsi"],100)
    def test_constant_and_partial_session(self):
        r=studies(self.rows(40,start=60,constant=True),60)
        self.assertEqual(r[-1]["rsi"],50);self.assertEqual(r[-1]["bb_upper"],100);self.assertEqual(r[-1]["macd_hist"],0);self.assertIsNone(r[-1]["vwap"])
        self.assertIsNone(studies(self.rows(2,step=86400),86400)[-1]["vwap"])
    def test_midnight_restart(self):
        r=studies(self.rows(4,start=86340),60)
        self.assertIsNone(r[0]["vwap"]);self.assertEqual(r[1]["vwap"],101)
