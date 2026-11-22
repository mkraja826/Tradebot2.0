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

    def test_uppercase_fire_id_rejected_before_vm_and_broker_checks(self):
        result = subprocess.run(
            ["bash", str(AUDIT), "A" * 32],
            capture_output=True, text=True, check=False, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Usage:", result.stderr)
        self.assertNotIn("SIGNED_ACCOUNT_IDENTITY_GET", result.stdout)

    def test_selected_fire_id_is_passed_to_historical_reconciliation(self):
        text = AUDIT.read_text(encoding="utf-8")
        self.assertIn(
            'tradebot.fire_reconciliation_phase_probe --data-dir "$DATA" --fire-id "$FIRE_ID"',
            text)
        self.assertIn(
            'tradebot.demo_release_evidence --data-dir "$DATA" --fire-id "$FIRE_ID"',
            text)
        self.assertIn("Historical receipt: selected existing local BTC FIRE", text)
        self.assertNotIn('Historical receipt: %s', text)

    def test_vm_source_provenance_and_clean_executables_are_required(self):
        text = AUDIT.read_text(encoding="utf-8")
        self.assertIn("MINIMUM_REVIEWED_BASE=", text)
        self.assertIn("git -C \"$ROOT\" merge-base --is-ancestor", text)
        self.assertIn(
            "git -C \"$ROOT\" status --porcelain --untracked-files=all -- src/tradebot ops",
            text)
        self.assertIn("source_integrity_cannot_be_checked", text)
        self.assertNotIn("git pull", text.replace(
            "# Only inspect git; NEVER pull/checkout/restart services from a diagnostic.",
            ""))
        self.assertNotIn("git checkout", text)
        self.assertNotIn("systemctl restart", text)

    def test_single_staged_audit_reports_all_independent_blockers(self):
        text = AUDIT.read_text(encoding="utf-8")
        self.assertIn('PY="${TRADEBOT_AUDIT_PYTHON:-$ROOT/.venv/bin/python}"', text)
        self.assertIn("reviewed_source_or_explicit_interpreter_unavailable", text)
        self.assertIn("tradebot.fire_exposure_only_probe", text)
        self.assertIn("tradebot.offhost_alerts --data-dir \"$DATA\" --check", text)
        self.assertIn("journal_present", text)
        self.assertIn("unsafe_permissions", text)
        self.assertIn("financial_analysis", (ROOT / "src" / "tradebot" /
                                              "fire_reconciliation_phase_probe.py").read_text())
        self.assertIn("TRADING_ENABLED: false", text)
        self.assertTrue(text.rstrip().endswith("exit 2"))
        for forbidden in ("chmod 600", "systemctl stop", "git reset",
                          "git switch", "git pull", "git checkout"):
            self.assertNotIn(forbidden, text.replace(
                "# Only inspect git; NEVER pull/checkout/restart services from a diagnostic.",
                ""))

    def test_free_remote_alert_options_checked_without_fake_delivery_or_new_network(self):
        text = AUDIT.read_text(encoding="utf-8")
        self.assertIn("run_optional_check 'Generic HTTPS", text)
        self.assertIn("OPTIONAL_NOT_CONFIGURED", text)
        self.assertIn("not a release gate", text)
        self.assertIn("tradebot.telegram_alerts tradebot2-telegram-alerts.service", text)
        self.assertIn("tradebot.healthchecks_ping tradebot2-healthchecks-ping.timer", text)
        self.assertIn('systemctl is-active --quiet "$unit"', text)
        self.assertIn('"$PY" -m "$module" --data-dir "$DATA" --check', text)
        self.assertIn("LOCAL_READY_REMOTE_DELIVERY_UNVERIFIED", text)
        self.assertIn("private_alert_configuration_unavailable", text)
        self.assertIn("real external Telegram incident delivery", text)
        for forbidden in ("--ping", "--test", "--baseline", "systemctl enable",
                          "systemctl start", "curl ", "wget ", "sendMessage"):
            self.assertNotIn(forbidden, text)
        self.assertIn("TRADING_ENABLED: false", text)

    def test_full_audit_never_runs_for_missing_directory_with_custom_python(self):
        import os
        with TemporaryDirectory() as tmp:
            result = subprocess.run(
                ["bash", str(AUDIT), "a"*32, str(Path(tmp) / "absent")],
                env={**os.environ, "TRADEBOT_AUDIT_PYTHON": "/bin/false"},
                capture_output=True, text=True, check=False, timeout=5)
            self.assertEqual(result.returncode, 2)
            self.assertIn("trusted_existing_data_directory_unavailable",
                          result.stderr)
            self.assertNotIn("SIGNED_ACCOUNT_IDENTITY_GET", result.stdout)

    def test_auth_check_precedes_broker_and_financial_checks(self):
        text = AUDIT.read_text(encoding="utf-8")
        auth = text.index("tradebot.delta_auth_diagnostic")
        broker = text.index("tradebot.fire_leverage_probe")
        finance = text.index("tradebot.fire_reconciliation_phase_probe")
        self.assertLess(auth, broker)
        self.assertLess(broker, finance)
        self.assertIn("TRADING_ENABLED: false", text)
        self.assertIn("exit 2", text)

    def test_only_get_only_existing_diagnostics_and_no_execution_switches(self):
        text = AUDIT.read_text(encoding="utf-8")
        for module in (
            "tradebot.fire_leverage_probe",
            "tradebot.equity_monitor",
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
        self.assertIn("risk_health(", text)
        self.assertIn("watchdog", text)
        self.assertIn("equity_collector", text)
        self.assertIn("TRADING_ENABLED: false", text)
        self.assertIn("exit 2", text)


if __name__ == "__main__":
    unittest.main()
