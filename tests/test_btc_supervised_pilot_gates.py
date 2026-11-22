"""Offline one-pass supervised BTC DEMO preflight and independence tests."""
from datetime import datetime, timezone
from unittest.mock import patch
from pathlib import Path
import tempfile
import unittest

from tradebot.btc_supervised_pilot_gates import (
    REQUIRED_BTC_PERIODS, ReadOnlyArchive, inspect_btc_pilot_gates,
)
from tradebot.delta import DEMO_API

NOW = datetime(2026, 11, 22, 17, tzinfo=timezone.utc)


class DummyReadOnly:
    base_url = DEMO_API
    allow_orders = False


def session_ok(*a, **kw):
    return {"status": "baseline_candidate_review_only",
            "session_budget_within_limits": True,
            "trade_authorized": False, "safe_to_enable_fire": False}


def account_ok(*a, **kw):
    return {"account_flat_verified": True, "open_positions": 0,
            "open_orders": 0, "checked_markets": ["BTCUSD", "XAUTUSD"]}


def quality_ok(*a, **kw):
    return {k: "provisionally_valid" for k in REQUIRED_BTC_PERIODS}


class PilotReadinessTests(unittest.TestCase):
    def run_gate(self, *, client=None, session=session_ok,
                 margin=lambda e: "isolated",
                 account=account_ok, quality=quality_ok):
        return inspect_btc_pilot_gates(
            client or DummyReadOnly(), "/not/read/in_fixture", now=NOW,
            session_fn=session, margin_fn=margin,
            account_fn=account, quality_fn=quality)

    def test_all_candidate_checks_cannot_authorize_trade(self):
        r = self.run_gate()
        self.assertEqual(r["status"], "candidate_checks_passed_not_release_authority")
        self.assertEqual(r["blockers"], [])
        self.assertTrue(r["session_candidate_passed"])
        self.assertTrue(r["account_wide_flatness_verified"])
        self.assertTrue(r["btc_required_periods_provisionally_valid"])
        for name in ("trade_authorized", "safe_to_enable_fire",
                     "order_mutations", "ledger_mutations", "archive_mutations",
                     "independent_btc_trade_price_verification",
                     "watchdog_protection_lifecycle_verified",
                     "durable_one_attempt_controller_commissioned"):
            self.assertFalse(r[name])

    def test_existing_main_account_margin_block_stops_flat_gate(self):
        called = []
        def must_not_call(*args, **kwargs):
            called.append(True)
            raise AssertionError("never call guarded exposure on missing margin")
        r = self.run_gate(
            margin=lambda e: (_ for _ in ()).throw(ValueError("unverified")),
            account=must_not_call)
        self.assertEqual(called, [])
        self.assertIn("account_signed_isolated_margin_unverified", r["blockers"])
        self.assertFalse(r["account_wide_flatness_verified"])

    def test_btc_previous_month_quality_blocks_without_gold_dependency(self):
        def bad_quality(*args, **kwargs):
            q = quality_ok()
            q["previous_month"] = "suspicious_extreme"
            return q
        r = self.run_gate(quality=bad_quality)
        self.assertEqual(r["btc_period_quality"]["previous_month"],
                         "suspicious_extreme")
        self.assertEqual(r["blockers"], ["btc_historical_integrity_unverified"])

    def test_account_wide_exposure_blocks_even_if_btc_is_flat(self):
        def other_exposure(*args, **kwargs):
            return {"account_flat_verified": True, "open_positions": 0,
                    "open_orders": 0, "checked_markets": ["BTCUSD"]}
        r = self.run_gate(account=other_exposure)
        self.assertIn("account_wide_exposure_unverified", r["blockers"])

    def test_live_pilot_does_not_pass_pre_wallet_clock_to_session(self):
        called=[]
        def session(exchange, data_dir, **kwargs):
            called.append(kwargs)
            return session_ok()
        result = inspect_btc_pilot_gates(
            DummyReadOnly(), "/unused",
            session_fn=session, margin_fn=lambda x: "isolated",
            account_fn=account_ok, quality_fn=quality_ok)
        self.assertEqual(called, [{}])
        self.assertTrue(result["session_candidate_passed"])

    def test_bad_session_cannot_pass_even_if_other_checks_pass(self):
        r = self.run_gate(
            session=lambda *a, **kw: {"status": "blocked",
                                     "session_budget_within_limits": False})
        self.assertIn("supervised_session_equity_unverified", r["blockers"])

    def test_wrong_client_never_touches_any_checker(self):
        for endpoint, allowed in ((DEMO_API, True),
                                  ("https://api.india.delta.exchange", False)):
            with self.subTest(endpoint=endpoint):
                client = DummyReadOnly()
                client.base_url, client.allow_orders = endpoint, allowed
                def fail(*a, **kw):
                    raise AssertionError("should not call")
                r = self.run_gate(client=client, session=fail,
                                  margin=fail, account=fail, quality=fail)
                self.assertEqual(r["blockers"], ["readonly_delta_demo_client_required"])

    def test_string_ticker_timestamp_uses_existing_market_parser(self):
        class DemoTicker(DummyReadOnly):
            def ticker(self, symbol):
                self.symbol_seen = symbol
                return {"symbol": "BTCUSD", "product_id": 27,
                        "mark_price": "61000.5",
                        "timestamp": str(int(NOW.timestamp()))}
        fake = DemoTicker()
        with patch("tradebot.btc_supervised_pilot_gates.ReadOnlyArchive") as archive:
            archive.return_value.levels.return_value = {
                "periods": {
                    key: {"quality_status": status}
                    for key, status in quality_ok().items()
                },
            }
            from tradebot.btc_supervised_pilot_gates import btc_required_period_quality
            result = btc_required_period_quality(fake, "/unused", now=NOW)
            self.assertEqual(result, quality_ok())
            self.assertEqual(fake.symbol_seen, "BTCUSD")
            archive.return_value.levels.assert_called_once()

    def test_stale_string_ticker_does_not_pass(self):
        class StaleTicker(DummyReadOnly):
            def ticker(self, symbol):
                return {"symbol": "BTCUSD", "product_id": 27,
                        "mark_price": "61000.5",
                        "timestamp": str(int(NOW.timestamp()) - 120)}
        from tradebot.btc_supervised_pilot_gates import btc_required_period_quality
        with self.assertRaisesRegex(ValueError, "btc_original_archive_or_quote_unverified"):
            btc_required_period_quality(StaleTicker(), "/unused", now=NOW)

    def test_missing_original_archive_is_not_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "absent.sqlite"
            with self.assertRaises(ValueError):
                ReadOnlyArchive(path)
            self.assertFalse(path.exists())

    def test_no_external_gates_hidden_by_first_failure(self):
        r = self.run_gate(
            session=lambda *a, **kw: (_ for _ in ()).throw(ValueError()),
            margin=lambda *a, **kw: "cross",
            quality=lambda *a, **kw: (_ for _ in ()).throw(ValueError()))
        self.assertEqual(r["blockers"], [
            "account_signed_isolated_margin_unverified",
            "btc_historical_integrity_unverified",
            "supervised_session_equity_unverified",
        ])

    def test_normal_fire_controller_not_changed(self):
        src = (Path(__file__).resolve().parents[1] /
               "src/tradebot/fire_execution.py").read_text()
        self.assertIn("self.equity_guard.require_verified_read(", src)
        module = (Path(__file__).resolve().parents[1] /
                  "src/tradebot/btc_supervised_pilot_gates.py").read_text()
        self.assertIn("return 2  # Diagnostic cannot authorize", module)
        self.assertNotIn("place_order(", module)
        self.assertNotIn("FireDemoController(", module)


if __name__ == "__main__":
    unittest.main()
