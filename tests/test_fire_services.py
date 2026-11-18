"""FIRE systemd scripts keep execution testnet-only and opt-in."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FireServiceTests(unittest.TestCase):
    def test_scripts_have_valid_bash_syntax(self):
        for rel in (
            "ops/run_fire_watchdog.sh",
            "ops/install_fire_watchdog_service.sh",
            "ops/enable_fire_demo.sh",
            "ops/disable_fire_demo.sh",
        ):
            with self.subTest(path=rel):
                result = subprocess.run(
                    ["bash", "-n", str(ROOT / rel)],
                    capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_fire_demo_cannot_be_enabled_without_active_watchdog(self):
        active = (ROOT / "ops/enable_fire_demo.sh").read_text()
        self.assertIn("YES-DELTA-DEMO", active)
        self.assertIn("systemctl is-active tradebot2-fire-watchdog", active)
        self.assertIn("TRADEBOT_DASHBOARD_ALLOWED_HOST=", active)
        self.assertIn("TRADEBOT_FIRE_DEMO_EXECUTION=true", active)
        self.assertIn("TRADEBOT_FIRE_MAX_CONTRACTS=1", active)
        self.assertNotIn("0.0.0.0", active)

    def test_disable_new_entries_does_not_stop_guard(self):
        disable = (ROOT / "ops/disable_fire_demo.sh").read_text()
        self.assertIn("fire-demo.conf", disable)
        self.assertNotIn("systemctl stop tradebot2-fire-watchdog", disable)
        self.assertNotIn("systemctl disable tradebot2-fire-watchdog", disable)

    def test_fire_guard_has_no_autonomous_trade_or_ai_permission(self):
        guard = (ROOT / "ops/run_fire_watchdog.sh").read_text()
        self.assertIn("export ENABLE_DEMO_ORDERS=false", guard)
        self.assertIn("tradebot.fire_watchdog", guard)
        self.assertNotIn("tradebot.fire_probe", guard)
        self.assertNotIn("--demo-execute", guard)
        self.assertNotIn("topbilling", guard.lower())


if __name__ == "__main__":
    unittest.main()
