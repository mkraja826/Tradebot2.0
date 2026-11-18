"""Learning service deploy guardrails; static checks never access credentials."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LearningServiceTests(unittest.TestCase):
    def test_learning_shell_scripts_parse(self):
        for script in ("ops/run_learning.sh", "ops/install_learning_service.sh"):
            with self.subTest(script=script):
                check = subprocess.run(["bash", "-n", str(ROOT / script)],
                                       capture_output=True, text=True)
                self.assertEqual(check.returncode, 0, check.stderr)

    def test_paid_ai_is_opt_in_and_exchange_mutations_stay_disabled(self):
        script = (ROOT / "ops/run_learning.sh").read_text()
        self.assertIn("export ENABLE_DEMO_ORDERS=false", script)
        self.assertIn('source "$KEY_FILE"', script)
        self.assertIn('TRADEBOT_KIMI_PAID_REVIEWS:-false', script)
        self.assertIn("--paid-kimi", script)
        self.assertNotIn("--demo-execute", script)
        self.assertNotIn("run --mode demo", script)
        self.assertIn("trade_learning_watch", script)

    def test_separate_reboot_safe_learning_unit(self):
        script = (ROOT / "ops/install_learning_service.sh").read_text()
        self.assertIn("tradebot2-learning.service", script)
        self.assertIn("Restart=always", script)
        self.assertIn("WantedBy=multi-user.target", script)
        self.assertIn("NoNewPrivileges=true", script)
        self.assertIn("UMask=0077", script)
        self.assertIn("TRADEBOT_KIMI_PAID_REVIEWS:-false", script)
        self.assertNotIn("--demo-execute", script)


if __name__ == "__main__":
    unittest.main()
