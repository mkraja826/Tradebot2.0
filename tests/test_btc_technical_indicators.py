"""Reference behaviors for completed 5m indicator calculations, no broker."""
import unittest

from tradebot.btc_technical_indicators import compute_technical_5m


def candles(kind="flat", volume=10):
    rows=[]
    for i in range(288):
        close=100+i if kind=="rising" else 100
        open_price=close-0.4 if kind=="rising" else close
        rows.append({"time":1700000100+i*300,"open":open_price,
                     "high":close+1,"low":open_price-1,
                     "close":close,"volume":volume})
    return rows


class TechnicalIndicatorTests(unittest.TestCase):
    def test_flat_candles_have_neutral_signals(self):
        out=compute_technical_5m(candles())
        self.assertEqual(out["rsi14"],50)
        self.assertEqual(out["adx14"]["adx14"],0)
        self.assertEqual(out["macd_12_26_9"]["histogram"],0)
        self.assertEqual(out["bollinger_20_2"]["middle"],100)
        self.assertEqual(out["bollinger_20_2"]["bandwidth_bps"],0)
        self.assertIsNone(out["bollinger_20_2"]["percent_b"])
        self.assertEqual(out["relative_volume20"]["ratio"],1)
        self.assertFalse(out["trade_authorized"])

    def test_consistent_uptrend_signals(self):
        out=compute_technical_5m(candles(kind="rising"))
        self.assertEqual(out["rsi14"],100)
        self.assertGreater(out["adx14"]["adx14"],95)
        self.assertGreater(out["adx14"]["plus_di14"],out["adx14"]["minus_di14"])
        self.assertGreater(out["macd_12_26_9"]["line"],0)
        self.assertGreater(out["bollinger_20_2"]["upper"],out["bollinger_20_2"]["middle"])
        self.assertGreater(out["bollinger_20_2"]["middle"],out["bollinger_20_2"]["lower"])

    def test_rvol_compares_completed_latest_with_prior_twenty(self):
        series=candles()
        series[-1]["volume"]=35
        out=compute_technical_5m(series)
        self.assertEqual(out["relative_volume20"]["ratio"],3.5)

    def test_zero_volume_makes_rvol_unavailable_not_fake(self):
        out=compute_technical_5m(candles(volume=0))
        self.assertEqual(out["relative_volume20"]["status"],
                         "unavailable_zero_baseline")
        self.assertIsNone(out["relative_volume20"]["ratio"])

    def test_invalid_and_out_of_order_candles_fail(self):
        for key,value in (("high",0),("low",-2),("volume",-1),("close",float("nan")),
                          ("open","bad"),("time",1700000111)):
            with self.subTest(field=key):
                series=candles()
                series[-1][key]=value
                with self.assertRaises(ValueError):
                    compute_technical_5m(series)

    def test_insufficient_history_fails(self):
        with self.assertRaisesRegex(ValueError,"history_incomplete"):
            compute_technical_5m(candles()[:20])
