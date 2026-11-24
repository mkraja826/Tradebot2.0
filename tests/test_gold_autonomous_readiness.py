"""Read-only Gold readiness regression tests."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tradebot.gold_autonomous_readiness import inspect


class GoldReadinessTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def preflight(self, root):
        return dict(status="eligible_read_only_no_order", blockers=[],
                    order_authorized=False, broker_mutations=False, ai_calls=0)

    def test_arm_failure_keeps_other_blockers_and_hides_exception(self):
        (self.root / "gold-auto-demo-halt").touch()
        with patch("tradebot.gold_autonomous_demo.receipts_safe", return_value=False), \
             patch("tradebot.gold_autonomous_demo.is_gold_armed",
                   side_effect=RuntimeError("private upstream detail")):
            r = inspect(self.root, preflight=self.preflight)
        self.assertEqual(r["status"], "blocked")
        self.assertEqual(r["blockers"], ["previous_gold_fire_needs_review",
            "gold_autonomous_arm_missing", "gold_isolated_halt_requires_review"])
        self.assertFalse(r["armed"])
        self.assertFalse(r["order_authorized"])
        self.assertFalse(r["broker_mutations"])
        self.assertEqual(r["ai_calls"], 0)
        self.assertNotIn("private upstream detail", str(r))

    def test_truthy_nonboolean_evidence_is_not_verified(self):
        with patch("tradebot.gold_autonomous_demo.receipts_safe", return_value="yes"), \
             patch("tradebot.gold_autonomous_demo.is_gold_armed", return_value=1):
            r = inspect(self.root, preflight=self.preflight)
        self.assertEqual(r["status"], "blocked")
        self.assertEqual(r["blockers"], ["previous_gold_fire_needs_review",
                                         "gold_autonomous_arm_missing"])
        self.assertFalse(r["order_authorized"])

    def test_halt_probe_failure_is_not_clearance(self):
        with patch("tradebot.gold_autonomous_demo.receipts_safe", return_value=True), \
             patch("tradebot.gold_autonomous_demo.is_gold_armed", return_value=True), \
             patch("tradebot.gold_autonomous_readiness.Path.exists",
                   side_effect=PermissionError("private path")):
            r = inspect(self.root, preflight=self.preflight)
        self.assertEqual(r["status"], "blocked")
        self.assertEqual(r["blockers"], ["gold_isolated_halt_state_unavailable"])
        self.assertFalse(r["order_authorized"])
        self.assertNotIn("private path", str(r))


if __name__ == "__main__":
    unittest.main()
