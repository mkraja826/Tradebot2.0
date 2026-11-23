"""Offline read-only tests for precise autonomous BTC demo readiness."""
import unittest
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

from tradebot.btc_autonomous_readiness import inspect
from tradebot.delta import DEMO_API


class FakeBroker:
    base_url = DEMO_API
    allow_orders = False


def good_preflight(_broker, _root):
    return {
        "status": "operator_review_candidate_only", "blockers": [],
        "supervised_session_verified": True,
        "recent_btc_history_local_quality_verified": True,
        "owner_declared_main_isolated_accepted": True,
        "signed_isolated_margin_verified": False,
        "account_wide_flatness_verified": True,
        "watchdog_and_collector_active": True,
        "both_dashboard_fire_endpoints_disabled": True,
        "trade_authorized": False,
    }


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.calls = []

    def broker(self, **kwargs):
        self.calls.append(kwargs)
        assert kwargs.get("allow_orders") is False
        return FakeBroker()

    def check(self, *, arm=False, receipts=False, preflight=good_preflight,
              broker=None):
        return inspect(
            self.root, broker_factory=broker or self.broker,
            preflight=preflight, armed=lambda: arm,
            receipts_safe=lambda root: receipts)

    def test_explicit_arm_and_previous_receipt_fail_closed(self):
        r = self.check()
        self.assertEqual(r["blockers"], [
            "owner_autonomous_arm_missing",
            "previous_fire_requires_operator_review",
        ])
        self.assertTrue(r["demo_broker_preflight_verified"])
        self.assertEqual([x["allow_orders"] for x in self.calls], [False])
        self.assertFalse(r["order_authorized"])
        self.assertFalse(r["broker_mutations"])
        self.assertEqual(r["ai_calls"], 0)

    def test_credential_forwarding_never_allows_mutation(self):
        values = {"DELTA_DEMO_API_KEY": "test-id", "DELTA_DEMO_API_SECRET": "fixture-only"}
        with patch.dict("os.environ", values):
            result = self.check(arm=True, receipts=True)
        self.assertEqual(result["status"], "eligible_read_only_no_order")
        self.assertEqual(self.calls[0]["api_key"], values["DELTA_DEMO_API_KEY"])
        self.assertEqual(self.calls[0]["api_secret"], values["DELTA_DEMO_API_SECRET"])
        self.assertIs(self.calls[0]["allow_orders"], False)
        self.assertNotIn("fixture-only", str(result))

    def test_fully_eligible_diagnostic_still_cannot_authorize_orders(self):
        r = self.check(arm=True, receipts=True)
        self.assertEqual(r["status"], "eligible_read_only_no_order")
        self.assertEqual(r["blockers"], [])
        self.assertFalse(r["order_authorized"])
        self.assertFalse(r["owner_margin_attestation_is_broker_proof"])

    def test_missing_live_broker_evidence_returns_specific_code(self):
        def bad(broker, root):
            return {**good_preflight(broker, root),
                    "status": "blocked", "blockers": [
                        "account_wide_exposure_unverified"]}
        r = self.check(arm=True, receipts=True, preflight=bad)
        self.assertEqual(r["status"], "blocked")
        self.assertEqual(r["blockers"], ["account_wide_exposure_unverified"])

    def test_unrecognized_broker_codes_fail_closed_without_leaking(self):
        def bad(broker, root):
            return {**good_preflight(broker, root),
                    "status": "blocked", "blockers": [
                        "secret private upstream text"]}
        r = self.check(arm=True, receipts=True, preflight=bad)
        self.assertEqual(r["blockers"], ["broker_preflight_evidence_incomplete"])
        self.assertNotIn("secret", str(r))

    def test_broker_exception_does_not_reveal_private_exception(self):
        def bad(broker, root):
            raise RuntimeError("private upstream token must not leak")
        r = self.check(arm=True, receipts=True, preflight=bad)
        self.assertEqual(r["blockers"], ["broker_preflight_unavailable"])
        self.assertNotIn("token", str(r))

    def test_wrong_broker_cannot_reach_preflight(self):
        class WrongBroker:
            base_url = "https://actual-broker.example"
            allow_orders = True
        r = self.check(arm=True, receipts=True,
                       broker=lambda **kw: WrongBroker(),
                       preflight=lambda *args: self.fail("bad broker used"))
        self.assertEqual(r["blockers"], ["readonly_delta_demo_client_required"])

    def test_halt_marker_remains_blocker_even_with_good_broker(self):
        (self.root / "btc-auto-demo-halt").touch()
        r = self.check(arm=True, receipts=True)
        self.assertEqual(r["blockers"], ["unattended_halt_requires_operator_review"])

    def test_missing_or_symlink_root_cannot_query_broker(self):
        missing = self.root / "missing"
        r = inspect(missing, broker_factory=lambda **kw: self.fail("queried broker"))
        self.assertEqual(r["blockers"], ["trusted_data_directory_missing"])
        target = self.root / "alias"
        target.symlink_to(self.root, target_is_directory=True)
        r = inspect(target, broker_factory=lambda **kw: self.fail("queried broker"))
        self.assertEqual(r["blockers"], ["trusted_data_directory_missing"])


if __name__ == "__main__":
    unittest.main()
