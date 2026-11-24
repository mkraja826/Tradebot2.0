"""Test the bounded testnet execution launcher and read-only remote flatness check."""
import subprocess
import unittest
from unittest.mock import Mock, patch
from pathlib import Path

from tradebot.pilot_verify import check_flat, main

ROOT = Path(__file__).resolve().parents[1]


class FakeAccount:
    def __init__(self, positions=(), orders=()):
        self.positions = list(positions)
        self.orders = list(orders)

    def btc_positions(self):
        return self.positions

    def open_orders(self):
        return self.orders


class PilotVerificationTests(unittest.TestCase):
    def test_empty_account_is_flat(self):
        self.assertTrue(check_flat(FakeAccount())["verified_flat"])

    def test_open_order_blocks_pilot(self):
        result = check_flat(FakeAccount(orders=[{"product_symbol": "BTCUSD"}]))
        self.assertFalse(result["verified_flat"])
        self.assertEqual(result["account_open_orders"], 1)

    def test_btc_position_blocks_pilot(self):
        result = check_flat(FakeAccount(positions=[{"size": "1"}]))
        self.assertFalse(result["verified_flat"])
        self.assertEqual(result["btc_open_positions"], 1)

    def test_zero_position_is_flat(self):
        self.assertTrue(check_flat(FakeAccount(positions=[{"size": "0"}]))["verified_flat"])

    def test_unclear_position_never_claims_flat(self):
        for position in ({"wrong_field": "2"}, {"size": "NaN"}, {"size": None}):
            with self.subTest(position=position):
                with self.assertRaises(ValueError):
                    check_flat(FakeAccount(positions=[position]))

    def test_double_read_when_initially_flat(self):
        ex = FakeAccount()
        with patch("tradebot.pilot_verify.DeltaDemo", return_value=ex), \
             patch("tradebot.pilot_verify.sleep") as sleep_call, \
             patch("tradebot.pilot_verify.print") as output:
            main()
        sleep_call.assert_called_once_with(2)
        self.assertTrue(output.called)

    def test_launcher_syntax_and_strict_configuration(self):
        script = (ROOT / "ops/run_supervised_demo_pilot.sh").read_text()
        check = subprocess.run(["bash", "-n", str(ROOT / "ops/run_supervised_demo_pilot.sh")],
                               capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr)
        self.assertIn("tradebot.pilot_verify", script)
        self.assertIn('systemctl is-active --quiet tradebot2-observe.service', script)
        self.assertIn('timeout --signal=TERM --kill-after=120s 1200s', script)
        self.assertIn('--ai-interval-seconds 3600', script)
        self.assertIn('--max-hold-minutes 5', script)
        self.assertIn('ENABLE_DEMO_ORDERS=true ALLOW_CRYPTO_24X7_DEMO=true', script)
        self.assertIn('--mode demo --schedule crypto-24x7 --demo-execute', script)
        self.assertIn('set +x', script)
        self.assertNotIn('sudo systemctl enable', script)


if __name__ == "__main__":
    unittest.main()
