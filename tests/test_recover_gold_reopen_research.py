import unittest
from recover_trading.gold_reopen_research import nominal_window,normalize_calendar,normalize_trade,compare,epoch,CALENDAR
class ReopenTests(unittest.TestCase):
    def test_dst_nominal(self):
        winter=nominal_window(epoch("2026-11-30T00:00:00Z"))
        summer=nominal_window(epoch("2026-07-20T00:00:00Z"))
        self.assertEqual(winter["regular_reopen_utc"],"2026-11-29T23:00:00+00:00")
        self.assertEqual(summer["regular_reopen_utc"],"2026-07-19T22:00:00+00:00")
    def test_same_contract_gap_only(self):
        raw={"venue":"CME_GLOBEX","product":"GC","contract":"GCZ2026","close_at":"2026-11-27T18:00:00Z","reopen_at":"2026-11-29T23:00:00Z","source_url":CALENDAR}
        c,o=epoch(raw["close_at"]),epoch(raw["reopen_at"]);cal=normalize_calendar(raw,c-3600)
        t={"venue":"CME_GLOBEX","product":"GC","contract":"GCZ2026","currency":"USD","unit":"troy_ounce","source_url":"https://example.org/feed"}
        a=normalize_trade({**t,"trade_at":"2026-11-27T17:59:50Z","price":"3500"},c-5)
        b=normalize_trade({**t,"trade_at":"2026-11-29T23:00:05Z","price":"3535"},o+10)
        r=compare(cal,a,b,o+20)
        self.assertEqual(r["observed_gap_bps"],100)
        self.assertIsNone(r["direction"])
        self.assertFalse(r["first_reopen_trade_verified"])
        self.assertEqual(compare(cal,a,{**b,"contract":"GCG2027"},o+20)["status"],"contract_mismatch")
        with self.assertRaises(ValueError):normalize_calendar(raw,c)
        with self.assertRaises(ValueError):normalize_trade({**t,"venue":"INDICATIVE_SPOT","trade_at":"2026-11-29T23:00:05Z","price":"3535"},o+10)
