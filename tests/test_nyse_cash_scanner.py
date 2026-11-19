"""DeepSeek-only official US stock cash-hours schedule; broker/fire stays separate."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from tradebot.ai import TradePlan
from tradebot.runner import BotRunner, RunnerConfig
from tradebot.session import SessionPhase, nyse_cash_is_open, session_phase
from test_runner import FakeExchange, make_snapshot


def utc(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


class NYSECashCalendarTests(unittest.TestCase):
    def test_winter_exact_open_and_close(self):
        self.assertFalse(nyse_cash_is_open(utc(2026, 11, 19, 14, 29)))
        self.assertTrue(nyse_cash_is_open(utc(2026, 11, 19, 14, 30)))
        self.assertTrue(nyse_cash_is_open(utc(2026, 11, 19, 20, 59)))
        self.assertFalse(nyse_cash_is_open(utc(2026, 11, 19, 21, 0)))

    def test_summer_dst_exact_open_and_close(self):
        self.assertFalse(nyse_cash_is_open(utc(2026, 7, 1, 13, 29)))
        self.assertTrue(nyse_cash_is_open(utc(2026, 7, 1, 13, 30)))
        self.assertTrue(nyse_cash_is_open(utc(2026, 7, 1, 19, 59)))
        self.assertFalse(nyse_cash_is_open(utc(2026, 7, 1, 20, 0)))

    def test_early_close_holidays_and_weekends(self):
        self.assertTrue(nyse_cash_is_open(utc(2026, 11, 27, 17, 59)))
        self.assertFalse(nyse_cash_is_open(utc(2026, 11, 27, 18, 0)))
        self.assertFalse(nyse_cash_is_open(utc(2026, 11, 26, 16, 0)))
        self.assertFalse(nyse_cash_is_open(utc(2026, 11, 21, 16, 0)))

    def test_naive_datetime_rejected(self):
        with self.assertRaises(ValueError):
            nyse_cash_is_open(datetime(2026, 11, 19, 14, 30))


class DeepSeekCashOnlyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.journal = str(Path(tmp.name) / "trades.jsonl")
        self.planner = Mock()
        self.planner.propose.return_value = TradePlan(
            "research", "The scanner may elect to wait", ())
        self.exchange = FakeExchange()
        self.instant = utc(2026, 11, 19, 14, 29)
        self.snapshot_fn = Mock(side_effect=self.synthetic_snapshot)

    def synthetic_snapshot(self, *a, **kw):
        snapshot = make_snapshot(self.instant)
        snapshot["session_phase"] = session_phase(self.instant).value
        return snapshot

    def runner(self):
        return BotRunner(
            self.exchange, self.planner,
            config=RunnerConfig(
                mode="observe", schedule="nyse",
                nyse_cash_scan_only=True,
                ai_interval_seconds=300,
                poll_seconds=60,
                journal_path=self.journal,
            ),
            now=lambda: self.instant,
            snapshot_fn=self.snapshot_fn,
        )

    def test_preopen_and_afterclose_never_query_market_or_ai(self):
        bot = self.runner()
        self.exchange.positions[1] = 2  # FIRE may hold BTC outside NYSE hours
        for instant in (utc(2026, 11, 19, 14, 29),
                        utc(2026, 11, 19, 21, 0),
                        utc(2026, 11, 21, 16, 0)):
            self.instant = instant
            result = bot.tick()
            self.assertEqual(result["action"], "nyse_cash_closed_no_ai")
        self.planner.propose.assert_not_called()
        self.snapshot_fn.assert_not_called()
        self.assertEqual(self.exchange.trades, [])

    def test_opens_at_bell_and_scans_once_every_five_minutes(self):
        bot = self.runner()
        self.instant = utc(2026, 11, 19, 14, 30)
        self.assertEqual(bot.tick()["action"], "preview")
        self.assertEqual(bot.tick()["action"], "cooldown")
        self.instant = utc(2026, 11, 19, 14, 34)
        self.assertEqual(bot.tick()["action"], "cooldown")
        self.instant = utc(2026, 11, 19, 14, 35)
        self.assertEqual(bot.tick()["action"], "preview")
        self.assertEqual(self.planner.propose.call_count, 2)
        self.assertEqual(self.exchange.trades, [])
        context = self.planner.propose.call_args.args[0]
        self.assertEqual(context["trading_schedule"], "nyse")

    def test_quota_blocks_ninth_paid_request_even_after_restart(self):
        bot = self.runner()
        for index in range(8):
            self.instant = utc(2026, 11, 19, 14, 30) + timedelta(minutes=5*index)
            self.assertEqual(bot.tick()["action"], "preview")
        self.assertEqual(self.planner.propose.call_count, 8)
        self.instant = utc(2026, 11, 19, 15, 10)
        self.assertEqual(self.runner().tick()["action"], "ai_budget_exhausted_no_ai")
        self.assertEqual(self.planner.propose.call_count, 8)
        self.assertEqual(self.exchange.trades, [])

    def test_final_fifteen_minutes_are_research_only(self):
        bot = self.runner()
        self.instant = utc(2026, 11, 19, 20, 50)  # 3:50 PM EST
        self.assertEqual(session_phase(self.instant), SessionPhase.FLATTEN)
        self.assertEqual(bot.tick()["action"], "preview")
        context = self.planner.propose.call_args.args[0]
        self.assertEqual(context["session_phase"], "trading")
        self.assertEqual(self.exchange.trades, [])
        self.instant = utc(2026, 11, 19, 21, 0)
        self.assertEqual(bot.tick()["action"], "nyse_cash_closed_no_ai")
        self.assertEqual(self.planner.propose.call_count, 1)

    def test_cannot_attach_cash_scanner_flag_to_order_mode_or_crypto(self):
        for mode, schedule in (("demo", "nyse"), ("observe", "crypto-24x7"),
                               ("demo", "crypto-24x7")):
            with self.subTest(mode=mode, schedule=schedule):
                with self.assertRaises(ValueError):
                    RunnerConfig(mode=mode, schedule=schedule,
                                 nyse_cash_scan_only=True)


if __name__ == "__main__":
    unittest.main()
