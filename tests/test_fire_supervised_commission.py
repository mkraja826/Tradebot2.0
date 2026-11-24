"""No-POST regression gates for supervised one-shot Gold commissioning."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from tradebot.fire_supervised_commission import (
    APPROVAL_PHRASE, ATTEMPT_FILE, run_operator_commission,
)


def gate():
    return {
        "ready_for_supervised_operator_review": True,
        "broker_flat_two_samples": True,
        "both_fire_endpoints_disabled": True,
        "watchdog_and_dashboard_active": True,
        "equity_prerequisites_verified": True,
        "trade_authorized": False,
        "broker_liquidation_price_verified": False,
        "blockers": [],
    }


class CommissioningOperatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.calls = []

    def broker(self, **kwargs):
        self.assertIs(kwargs["allow_orders"], False)
        self.calls.append("read_only_broker")
        return object()

    def controller(self, *args, **kwargs):
        self.assertEqual(args[0], self.root / "fire-xaut.sqlite")
        self.assertTrue(kwargs["enabled"])
        self.assertEqual(kwargs["symbol"], "XAUTUSD")
        self.calls.append("controller")
        class FakeDesk:
            def start(self_inner):
                self.calls.append("start")
                return True, "accepted"
            def snapshot(self_inner):
                return {"status": "rejected_no_order", "orders_submitted": False,
                        "protection_verified": False,
                        "liquidation_verified": False, "press": "abc"}
        return FakeDesk()

    def run_trial(self, *, execute=False, approval=None, result=None):
        return run_operator_commission(
            self.root, execute=execute, approval=approval,
            broker_factory=self.broker,
            readiness=lambda broker, root: gate() if result is None else result,
            controller_factory=self.controller,
        )

    def test_default_is_read_only_and_does_not_consume_one_shot(self):
        value = self.run_trial()
        self.assertFalse(value["trade_authorized"])
        self.assertFalse(value["order_submitted"])
        self.assertTrue(value["can_request_operator_approval"])
        self.assertEqual(self.calls, ["read_only_broker"])
        self.assertFalse((self.root / ATTEMPT_FILE).exists())

    def test_approval_phrase_required_before_any_controller(self):
        for phrase in (None, "yes", "EXECUTE BTC FIRE"):
            with self.subTest(phrase=phrase):
                with self.assertRaises(ValueError):
                    self.run_trial(execute=True, approval=phrase)
                self.assertNotIn("controller", self.calls)
        self.assertFalse((self.root / ATTEMPT_FILE).exists())

    def test_failed_gate_blocks_before_marker_and_order(self):
        result = gate()
        result["watchdog_and_dashboard_active"] = False
        with self.assertRaises(ValueError):
            self.run_trial(execute=True, approval=APPROVAL_PHRASE, result=result)
        self.assertFalse((self.root / ATTEMPT_FILE).exists())
        self.assertNotIn("controller", self.calls)

    def test_missing_equity_approval_does_not_consume_attempt(self):
        result = gate()
        result.pop("equity_prerequisites_verified")
        with self.assertRaises(ValueError):
            self.run_trial(execute=True, approval=APPROVAL_PHRASE, result=result)
        self.assertFalse((self.root / ATTEMPT_FILE).exists())
        self.assertNotIn("controller", self.calls)

    def test_existing_one_shot_blocks_second_execution(self):
        first = self.run_trial(execute=True, approval=APPROVAL_PHRASE)
        self.assertTrue(first["request_accepted"])
        self.assertFalse(first["order_submitted"])
        self.assertFalse(first["trade_authorized"])
        self.assertEqual(first["status"], "rejected_no_order")
        self.assertTrue((self.root / ATTEMPT_FILE).exists())
        self.assertEqual(self.calls.count("start"), 1)
        with self.assertRaises(FileExistsError):
            self.run_trial(execute=True, approval=APPROVAL_PHRASE)
        self.assertEqual(self.calls.count("start"), 1)

    def test_no_broker_if_directory_missing(self):
        with self.assertRaises(ValueError):
            run_operator_commission(self.root / "nope",
                                    broker_factory=self.broker)
        self.assertEqual(self.calls, [])

    def test_consumed_or_broken_symlink_lock_never_offers_approval(self):
        marker = self.root / ATTEMPT_FILE
        marker.symlink_to(self.root / "absent")
        report = self.run_trial()
        self.assertTrue(report["one_shot_consumed"])
        self.assertFalse(report["can_request_operator_approval"])
        self.assertIn("gold_commissioning_lock_consumed", report["blockers"])
        with self.assertRaises(FileExistsError):
            self.run_trial(execute=True, approval=APPROVAL_PHRASE)
        self.assertTrue(marker.is_symlink())
        self.assertNotIn("controller", self.calls)

    def test_directory_sync_failure_preserves_lock_without_starting_controller(self):
        with patch("tradebot.fire_supervised_commission.os.fsync", side_effect=[None, OSError("disk failure")]):
            with self.assertRaises(OSError):
                self.run_trial(execute=True, approval=APPROVAL_PHRASE)
        self.assertTrue((self.root / ATTEMPT_FILE).exists())
        self.assertNotIn("controller", self.calls)
        with self.assertRaises(FileExistsError):
            self.run_trial(execute=True, approval=APPROVAL_PHRASE)

    def test_concurrent_operator_calls_cannot_both_consume_one_shot(self):
        def invoke(_):
            try:
                self.run_trial(execute=True, approval=APPROVAL_PHRASE)
                return 1
            except FileExistsError:
                return 0
        with ThreadPoolExecutor(max_workers=4) as workers:
            self.assertEqual(sum(workers.map(invoke, range(8))), 1)
        self.assertEqual(self.calls.count("start"), 1)

    def test_symlinked_data_directory_rejected_before_broker_or_controller(self):
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            run_operator_commission(alias, broker_factory=self.broker)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
