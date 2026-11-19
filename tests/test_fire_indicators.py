import unittest

from tradebot.fire_indicators import indicators


class FireIndicatorsTest(unittest.TestCase):
    end = 172800 + 7200

    def rows(self):
        return [{"time": t, "high": 102, "low": 98, "close": 100, "volume": 2}
                for t in range(self.end-48*3600, self.end, 300)]

    def test_both_trends_and_session_ignore_forming_bar(self):
        rows = self.rows()
        rows.append(dict(rows[-1], time=self.end, high=9999, close=9900))
        c = indicators(reversed(rows), self.end+42, 105)
        self.assertEqual(c["ema_15m"], c["ema_1h"])
        self.assertEqual(c["ema_1h"], {"ema20":100, "slope":"flat", "close":100})
        self.assertEqual((c["session_vwap"], c["atr_5m"]), (100, 4))

    def test_gap_and_midnight(self):
        c = indicators(self.rows()[:-1], self.end, 100)
        self.assertIsNone(c["atr_5m"])
        self.assertIsNone(c["session_vwap"])
        self.assertIsNone(c["ema_1h"])
        self.assertIsNone(indicators(self.rows(), 172800, 100)["session_vwap"])

    def test_reentry_uses_only_whole_bars_after_exit(self):
        rows = self.rows()
        rows[-2]["high"] = 110
        c = indicators(rows, self.end, 102, {"at": self.end-500, "price": 100})
        self.assertEqual(c["since_exit"]["move"], 2)
        self.assertFalse(c["since_exit"]["broke_pre_exit_high"])
        self.assertIsNotNone(c["since_exit"]["move_atr"])
