"""Release gate always uses two independently signed read-only samples."""
import unittest

from tradebot.fire_release_gate import verify_staging_samples
from test_demo_upgrade_preflight import FakeReadOnly, DemoUpgradePreflightTests
from tradebot.fire_execution import FireTradeStore
from tempfile import TemporaryDirectory
from pathlib import Path


class ProfileReadOnly(FakeReadOnly):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.account_margin_mode = "isolated"

    def _request(self, method, path, *, auth=False, params=None):
        if method == "GET" and path == "/v2/users/trading_preferences" and auth:
            self.calls.append((method, path))
            return {"result": {"user_id": 501}}
        if method == "GET" and path == "/v2/sub_accounts" and auth:
            self.calls.append((method, path))
            return {"result": [{"id": 501, "margin_mode": self.account_margin_mode}]}
        return super()._request(method, path, auth=auth, params=params)


class TwoPassReleaseGateTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        FireTradeStore(self.root / "fire-ops.sqlite")
        FireTradeStore(self.root / "fire-xaut.sqlite")

    def observe(self, broker, *, after_first=None, delays=None):
        clock = [100.0]
        def advance(seconds):
            if delays is not None:
                delays.append(seconds)
            clock[0] += seconds
            if after_first:
                after_first()
        return verify_staging_samples(
            broker, self.root, pause=advance, monotonic=lambda: clock[0])

    def test_two_distinct_signed_read_only_samples_allow_staging_only(self):
        fake = ProfileReadOnly()
        delays = []
        result = self.observe(fake, delays=delays)
        self.assertEqual(delays, [11])
        self.assertEqual(result["samples_checked"], 2)
        self.assertTrue(result["broker_flat_two_samples"])
        self.assertTrue(result["sample_interval_verified"])
        self.assertFalse(result["operator_may_stage_only_if_fire_disabled_and_watchdog_healthy"])
        self.assertEqual(fake.calls.count(("GET", "/v2/users/trading_preferences")), 2)
        self.assertEqual(fake.calls.count(("GET", "/v2/sub_accounts")), 2)
        self.assertFalse(any("/v2/profile" in p for _, p in fake.calls))
        self.assertFalse(result["safe_to_enable_fire"])
        self.assertFalse(result["order_mutations"])
        self.assertEqual(result["ai_calls"], 0)
        self.assertEqual(fake.calls.count(("GET", "/v2/positions/margined")), 2)
        self.assertEqual(fake.calls.count(("GET", "/v2/positions")), 4)
        self.assertTrue(all(method == "GET" for method, _ in fake.calls))

    def test_100x_is_reported_but_staging_not_permission_to_fire(self):
        fake = ProfileReadOnly(btc_lev=100, gold_lev=100)
        report = self.observe(fake)
        self.assertIn("broker_leverage_above_20x_btcusd", report["blockers"])
        self.assertTrue(report["broker_flat_two_samples"])
        self.assertFalse(report["safe_to_enable_fire"])

    def test_new_position_between_samples_fails_closed(self):
        fake = ProfileReadOnly()
        def race(_):
            fake.realtime_positions = [{"product_id": 27, "size": "-8"}]
        report = self.observe(fake, after_first=lambda: race(11))
        self.assertEqual(report["samples_checked"], 2)
        self.assertIn("realtime_market_exposure_btcusd", report["blockers"])
        self.assertFalse(report["broker_flat_two_samples"])

    def test_open_order_on_second_sample_fails_closed(self):
        fake = ProfileReadOnly()
        def race(_):
            fake.orders = [{"id": 22, "product_id": 888}]
        report = self.observe(fake, after_first=lambda: race(11))
        self.assertFalse(report["broker_flat_two_samples"])
        self.assertIn("account_has_open_orders", report["blockers"])

    def test_nonisolated_profile_blocks_staging(self):
        fake = ProfileReadOnly()
        fake.account_margin_mode = "portfolio"
        report = self.observe(fake)
        self.assertFalse(report["broker_flat_two_samples"])
        self.assertIn("account_isolated_margin_not_verified", report["blockers"])

    def test_first_sample_broker_failure_does_not_wait(self):
        fake = ProfileReadOnly(realtime_unavailable=True)
        called = []
        report = verify_staging_samples(fake, self.root, pause=called.append)
        self.assertEqual(report["samples_checked"], 1)
        self.assertFalse(report["broker_flat_two_samples"])
        self.assertEqual(called, [])

    def test_pause_that_does_not_actually_wait_cannot_claim_two_samples(self):
        fake = ProfileReadOnly()
        # A callback that immediately returns isn't an eleven-second delay.
        report = verify_staging_samples(
            fake, self.root, pause=lambda _: None,
            monotonic=lambda: 100.0)
        self.assertEqual(report["samples_checked"], 1)
        self.assertFalse(report["sample_interval_verified"])
        self.assertIn("sample_spacing_not_verified", report["blockers"])
        self.assertFalse(report["broker_flat_two_samples"])
        self.assertFalse(report["operator_may_stage_only_if_fire_disabled_and_watchdog_healthy"])

    def test_missing_signed_identity_never_fakes_isolated_account(self):
        fake = ProfileReadOnly()
        def broken(method, path, *, auth=False, params=None):
            if path == "/v2/sub_accounts":
                return {"result": [{"id": 12345, "margin_mode": "isolated"}]}
            return ProfileReadOnly._request(
                fake, method, path, auth=auth, params=params)
        fake._request = broken
        report = self.observe(fake)
        self.assertIn("signed_preflight_unavailable", report["blockers"])
        self.assertFalse(report["broker_flat_two_samples"])

    def test_pause_exception_blocks_staging(self):
        fake = ProfileReadOnly()
        def fail(_):
            raise RuntimeError("sentinel secret")
        report = verify_staging_samples(fake, self.root, pause=fail)
        self.assertEqual(report["samples_checked"], 1)
        self.assertIn("sample_interval_not_completed", report["blockers"])
        self.assertNotIn("sentinel secret", str(report))
        self.assertFalse(report["broker_flat_two_samples"])


if __name__ == "__main__":
    unittest.main()
