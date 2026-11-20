"""Offline regression for VM FIRE opt-out scripts (never executes systemctl)."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
DISABLE = ROOT / "ops" / "disable_fire_demo.sh"
ENABLE = ROOT / "ops" / "enable_fire_demo.sh"


class FireControlScriptsTest(unittest.TestCase):
    def test_script_syntax(self):
        for path in (DISABLE, ENABLE):
            with self.subTest(script=path.name):
                proc = subprocess.run(["bash", "-n", str(path)],
                                      text=True, capture_output=True, check=False)
                self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_disable_must_explicitly_unset_and_confirm_both_markets(self):
        script = DISABLE.read_text()
        self.assertIn("UnsetEnvironment=TRADEBOT_FIRE_DEMO_EXECUTION", script)
        self.assertIn("99-fire-disabled.conf", script)
        self.assertIn("/api/fire/XAUTUSD", script)
        self.assertIn('receipt.get("execution_enabled") is not False', script)
        self.assertIn("tradebot2-fire-watchdog", script)
        self.assertNotIn("stop tradebot2-fire-watchdog", script)

    def test_enable_refuses_override_while_disabled(self):
        script = ENABLE.read_text()
        self.assertIn("99-fire-disabled.conf", script)
        self.assertIn("Supervised risk commissioning is required", script)


if __name__ == "__main__":
    unittest.main()
