"""Offline checks for the operator's fail-closed, read-only BTC audit launcher."""
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "ops" / "run_btc_demo_release_audit.sh"


class BtcReadOnlyAuditTests(unittest.TestCase):
    def test_launcher_shell_syntax(self):
        completed = subprocess.run(
            ["bash", "-n", str(AUDIT)], capture_output=True, text=True,
            check=False, timeout=5)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_invalid_receipt_rejected_before_any_broker_or_model_calls(self):
        result = subprocess.run(
            ["bash", str(AUDIT), "not-an-id"],
            capture_output=True, text=True, check=False, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Usage:", result.stderr)
        self.assertNotIn("TRADING_ENABLED: true", result.stdout)

    def test_missing_data_is_fail_closed_and_no_directory_is_created(self):
        with TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing"
            result = subprocess.run(
                ["bash", str(AUDIT), "a"*32, str(missing)],
                capture_output=True, text=True, check=False, timeout=5)
            self.assertEqual(result.returncode, 2)
            self.assertIn("trusted_existing_data_directory_unavailable",
                          result.stderr)
            self.assertFalse(missing.exists())

    def test_only_get_only_existing_diagnostics_and_no_execution_switches(self):
        text = AUDIT.read_text(encoding="utf-8")
        for module in (
            "tradebot.fire_leverage_probe",
            "tradebot.equity_checkpoint_health",
            "tradebot.candle_anomaly_inventory",
            "tradebot.fire_reconciliation_phase_probe",
            "tradebot.demo_release_evidence",
        ):
            self.assertIn(module, text)
        for forbidden in (
            "tradebot.fire_demo", "fire_demo(", "--execute-one",
            "enable_fire_demo.sh", "disable_fire_demo.sh",
            "systemctl restart", "systemctl start", "POST /v2/orders",
            "ALLOW_CRYPTO_24X7_DEMO=true",
            "TRADEBOT_FIRE_DEMO_EXECUTION=true",
            "TRADING_ENABLED: true",
        ):
            self.assertNotIn(forbidden, text)
        self.assertIn("allow_orders=False", (ROOT / "src" / "tradebot" /
                                             "fire_reconciliation_phase_probe.py").read_text())
        self.assertIn("TRADING_ENABLED: false", text)
        self.assertIn("exit 2", text)


if __name__ == "__main__":
    unittest.main()
