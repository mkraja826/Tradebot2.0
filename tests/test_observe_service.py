"""Deployment smoke checks that never require sudo, secrets or a VM."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ObserveServiceTests(unittest.TestCase):
    def test_shell_scripts_parse(self):
        for script in ("ops/run_observe.sh", "ops/install_observe_service.sh"):
            with self.subTest(script=script):
                completed = subprocess.run(
                    ["bash", "-n", str(ROOT / script)],
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_launcher_is_forced_to_observe_mode(self):
        script = (ROOT / "ops/run_observe.sh").read_text()
        self.assertIn('export ENABLE_DEMO_ORDERS=false', script)
        self.assertIn('run --mode observe', script)
        self.assertIn('--poll-seconds 60', script)
        self.assertIn('--ai-interval-seconds 300', script)
        self.assertIn('--schedule crypto-24x7', script)
        self.assertIn('--max-options 32', script)
        self.assertNotIn('run --mode demo', script)
        self.assertNotIn('--demo-execute', script)
        self.assertIn('source "$KEY_FILE"', script)
        self.assertIn('umask 077', script)
        self.assertNotIn('echo "$TB_API_KEY"', script)

    def test_installer_provides_crash_and_reboot_recovery(self):
        script = (ROOT / "ops/install_observe_service.sh").read_text()
        self.assertIn('Restart=always', script)
        self.assertIn('RestartSec=45', script)
        self.assertIn('WantedBy=multi-user.target', script)
        self.assertIn('User=$VM_USER', script)
        self.assertIn('ExecStart=/usr/bin/bash $PROJECT/ops/run_observe.sh', script)
        self.assertIn('sudo systemctl enable "$UNIT_NAME"', script)
        self.assertIn('sudo systemctl restart "$UNIT_NAME"', script)
        self.assertIn('UMask=0077', script)
        self.assertIn('NoNewPrivileges=true', script)
        self.assertNotIn('EnvironmentFile=', script)
        self.assertNotIn('--demo-execute', script)


if __name__ == "__main__":
    unittest.main()
