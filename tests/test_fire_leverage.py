"""Offline regression gates for adaptive GPT-6 demo leverage and liquidation."""
import unittest

from tradebot.fire_leverage import (
    LeverageRejected, synchronize_leverage, verify_liquidation_clearance
)
from test_fire_execution import FakeDemo


class DynamicLeverageTests(unittest.TestCase):
    def setUp(self):
        self.broker = FakeDemo()
        self.plan = {"direction": "LONG", "contracts": 1,
                     "leverage": 5, "stop_loss": "62950", "take_profit": "63950"}
        self.position = {"product_id": 27, "size": 1, "entry_price": "63214.25"}

    def test_leverage_changes_once_and_readback_matches(self):
        self.assertEqual(synchronize_leverage(self.broker, 27, 3), 3)
        self.assertEqual(self.broker.leverage, 3)
        self.assertEqual(self.broker.leverage_changes, [{"leverage": "3"}])
        self.assertEqual(synchronize_leverage(self.broker, 27, 3), 3)
        self.assertEqual(len(self.broker.leverage_changes), 1)

    def test_gpt_cannot_override_20x_or_use_invalid_value(self):
        for selected in (0, 21, 100, True, 2.5, "10"):
            with self.subTest(selected=selected), self.assertRaises(LeverageRejected):
                synchronize_leverage(self.broker, 27, selected)
        self.assertFalse(self.broker.leverage_changes)

    def test_no_mutation_of_legacy_100x_setting(self):
        self.broker.leverage = 100
        with self.assertRaises(LeverageRejected):
            synchronize_leverage(self.broker, 27, 5)
        self.assertEqual(self.broker.leverage, 100)
        self.assertFalse(self.broker.leverage_changes)

    def test_leverage_readback_mismatch_fails_closed(self):
        self.broker.ignore_leverage_change = True
        with self.assertRaises(LeverageRejected):
            synchronize_leverage(self.broker, 27, 3)
        self.assertEqual(self.broker.leverage, 5)

    def test_open_position_or_orders_blocks_mutation(self):
        self.broker.position = 1
        with self.assertRaises(LeverageRejected):
            synchronize_leverage(self.broker, 27, 3)
        self.broker.position = 0
        self.broker.active_orders = [{"id": 9, "product_id": 27}]
        with self.assertRaises(LeverageRejected):
            synchronize_leverage(self.broker, 27, 3)
        self.assertFalse(self.broker.leverage_changes)

    def test_liquidation_requires_isolated_position_and_buffer(self):
        self.broker.position = 1
        proof = verify_liquidation_clearance(self.broker, 27, self.plan, self.position)
        self.assertEqual(proof["liquidation_price"], "60000")
        self.assertTrue(proof["liquidation_verified"])
        self.broker.liquidation_price = "62700"
        with self.assertRaises(LeverageRejected):
            verify_liquidation_clearance(self.broker, 27, self.plan, self.position)
        self.broker.liquidation_price = "60000"
        self.broker.margin_mode = "portfolio"
        with self.assertRaises(LeverageRejected):
            verify_liquidation_clearance(self.broker, 27, self.plan, self.position)

    def test_missing_margin_evidence_is_never_safe_by_default(self):
        self.broker.position = 1
        self.broker.liquidation_price = None
        with self.assertRaises(LeverageRejected):
            verify_liquidation_clearance(self.broker, 27, self.plan, self.position)


if __name__ == "__main__":
    unittest.main()
