"""No-network, no-ledger coverage of the diagnostic-only broker presence probe."""
import unittest
from unittest.mock import patch

from tradebot.delta import DEMO_API
from tradebot.demo_broker_presence import (
    _valid_sample, observe_demo_broker_presence, main,
)


class ReadOnlyDemo:
    base_url = DEMO_API
    allow_orders = False


def flat():
    return {
        "isolated_margin_observed": True,
        "account_margined_nonzero_positions": 0,
        "account_open_orders": 0,
        "realtime_fire_sizes": {"BTCUSD": "0", "XAUTUSD": "0"},
        "fire_product_ids": {"BTCUSD": 1, "XAUTUSD": 2},
        "margined_fire_consistency": True,
    }


class BrokerPresenceTests(unittest.TestCase):
    def setUp(self):
        self.exchange = ReadOnlyDemo()
        self.t = 100.0
        self.reads = []

    def tick(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds

    def observe(self, samples=None, **kw):
        chosen = samples if samples is not None else [flat(), flat()]
        it = iter(chosen)

        def sample(exchange):
            self.assertIs(exchange, self.exchange)
            self.assertIs(exchange.allow_orders, False)
            self.reads.append("GET-only-sampler")
            return next(it)

        options = {"sampler": sample, "pause": self.sleep,
                   "monotonic": self.tick}
        options.update(kw)
        return observe_demo_broker_presence(self.exchange, **options)

    def test_two_consistent_flat_reads_are_never_release_authority(self):
        result = self.observe()
        self.assertEqual(result["status"],
                         "two_flat_broker_snapshots_only_not_release_authority")
        self.assertEqual(result["samples_checked"], 2)
        self.assertTrue(result["sample_spacing_verified"])
        self.assertEqual(self.t, 111.0)
        self.assertEqual(len(self.reads), 2)
        for field in ("trade_authorized", "safe_to_enable_fire",
                      "ready_for_unattended_trading", "broker_order_mutations",
                      "local_ledger_mutations", "local_reconciliation_complete",
                      "historical_gold_order_verified"):
            self.assertIs(result[field], False, field)

    def test_read_only_client_required_before_any_reads(self):
        for name, bad in (("allow_orders", True), ("base_url", "https://live.invalid")):
            with self.subTest(name=name):
                setattr(self.exchange, name, bad)
                result = self.observe()
                self.assertEqual(result["blockers"], [
                    "read_only_delta_demo_client_required"
                ])
                self.assertEqual(self.reads, [])
                setattr(self.exchange, name,
                        False if name == "allow_orders" else DEMO_API)

    def test_account_open_orders_or_positions_block(self):
        for field in ("account_open_orders",
                      "account_margined_nonzero_positions"):
            with self.subTest(field=field):
                state = {**flat(), field: 1}
                result = self.observe(samples=[state, state])
                self.assertTrue(result["blockers"])
                self.assertEqual(result["status"], "blocked_or_unverified")

    def test_btc_or_gold_realtime_size_blocks(self):
        for symbol in ("BTCUSD", "XAUTUSD"):
            with self.subTest(symbol=symbol):
                s = flat()
                s["realtime_fire_sizes"] = {**s["realtime_fire_sizes"],
                                            symbol: "-1"}
                r = self.observe(samples=[s, s])
                self.assertIn("btc_or_gold_position_exposure_present",
                              r["blockers"])

    def test_nonisolated_or_mismatched_sources_block(self):
        for field in ("isolated_margin_observed", "margined_fire_consistency"):
            with self.subTest(field=field):
                s = {**flat(), field: False}
                result = self.observe(samples=[s, s])
                self.assertNotEqual(result["blockers"], [])
                self.assertFalse(result["trade_authorized"])

    def test_changed_account_state_blocks_even_if_final_flat(self):
        a = flat()
        b = {**flat(), "account_open_orders": 1}
        result = self.observe(samples=[a, b])
        self.assertIn("broker_state_changed_between_samples",
                      result["blockers"])
        self.assertIn("account_open_orders_present", result["blockers"])

    def test_short_time_interval_does_not_accept_two_sweeps(self):
        r = self.observe(pause=lambda seconds: self.sleep(seconds - 1))
        self.assertEqual(r["samples_checked"], 1)
        self.assertIn("sample_spacing_unverified", r["blockers"])
        self.assertEqual(len(self.reads), 1)

    def test_missing_second_response_or_exception_is_sanitized(self):
        def bad_sample(_):
            self.reads.append("called")
            raise RuntimeError("SECRET_PRIVATE_API_KEY")
        r = self.observe(sampler=bad_sample)
        self.assertIn("authenticated_broker_read_unavailable", r["blockers"])
        self.assertNotIn("SECRET_PRIVATE_API_KEY", str(r))
        self.assertEqual(r["samples_checked"], 0)

    def test_invalid_schema_is_fail_closed(self):
        for value in ("NaN", "1.5", None, {}, True):
            with self.subTest(value=value):
                s = flat()
                s["realtime_fire_sizes"]["BTCUSD"] = value
                self.assertFalse(_valid_sample(s))
        s = flat()
        s["fire_product_ids"]["XAUTUSD"] = 1
        self.assertFalse(_valid_sample(s))
        s = flat()
        del s["realtime_fire_sizes"]["XAUTUSD"]
        self.assertFalse(_valid_sample(s))

    def test_missing_credentials_do_not_instantiate_broker(self):
        with patch.dict("os.environ",
                        {"DELTA_DEMO_API_KEY": "", "DELTA_DEMO_API_SECRET": ""},
                        clear=False):
            with patch("tradebot.demo_broker_presence.DeltaDemo") as cls:
                with patch("builtins.print"):
                    self.assertEqual(main([]), 2)
                cls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
