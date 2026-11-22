"""Stage-only watchdog service installer must never change active protection."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "ops/install_fire_watchdog_service.sh"


class StageWatchdogUnitTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="watchdog-stage-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.project = self.root / "project"
        self.home = self.root / "vm-home"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.home.mkdir()
        (self.project / "ops").mkdir(parents=True)
        (self.project / "src/tradebot").mkdir(parents=True)
        (self.project / ".venv/bin").mkdir(parents=True)
        (self.project / "data").mkdir(parents=True)
        self.installer = self.project / "ops/install_fire_watchdog_service.sh"
        self.installer.write_text(SCRIPT.read_text())
        self.installer.chmod(0o700)
        (self.project / "src/tradebot/fire_watchdog.py").write_text("# fake\n")
        (self.project / "ops/run_fire_watchdog.sh").write_text("# fake\n")
        interpreter = self.project / ".venv/bin/python"
        interpreter.write_text("#!/usr/bin/env bash\nexit 97\n")
        interpreter.chmod(0o700)
        for name in ("fire-ops.sqlite", "fire-xaut.sqlite",
                     "fire-monitoring.sqlite"):
            (self.project / "data" / name).write_bytes(b"ORIGINAL_UNCHANGED")
        keys = self.home / ".config/tradebot2/keys.env"
        keys.parent.mkdir(parents=True)
        keys.write_text("PRIVATE_CREDENTIAL_FILE_SHOULD_NOT_BE_OPENED\n")
        keys.chmod(0o600)
        self.keys = keys
        self.external_calls = self.root / "external_called"
        self.set_fake_id("1001")
        for program in ("sudo", "systemctl"):
            mock = self.bin / program
            mock.write_text(
                "#!/usr/bin/env bash\n"
                f"printf 'invoked' >> '{self.external_calls}'\n"
                "exit 99\n"
            )
            mock.chmod(0o700)

    def set_fake_id(self, uid):
        mock = self.bin / "id"
        mock.write_text(
            "#!/usr/bin/env bash\n"
            f"case \"$1\" in -u) printf '{uid}\\n';; "
            "-un|-gn) printf 'testoperator\\n';; *) exit 99;; esac\n"
        )
        mock.chmod(0o700)

    def run_installer(self):
        return subprocess.run(
            ["bash", str(self.installer)],
            env={**os.environ, "HOME": str(self.home),
                 "PATH": str(self.bin) + ":/usr/bin:/bin"},
            capture_output=True, text=True, check=False, timeout=8,
        )

    def test_active_watchdog_cannot_be_restarted_or_replaced(self):
        # The mock systemctl/sudo commands would record ANY touch, even on
        # an otherwise active watchdog. No broker, VM, or testnet involved.
        originals = {p.name: p.read_bytes()
                     for p in (self.project / "data").iterdir()}
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.external_calls.exists())
        self.assertIn("WATCHDOG_RESTARTED: false", result.stdout)
        self.assertIn("TRADING_ENABLED: false", result.stdout)
        stage = self.home / ".config/tradebot2/staged-units"
        candidates = list(stage.iterdir())
        self.assertEqual(len(candidates), 1)
        unit = candidates[0]
        self.assertRegex(unit.name, r"^tradebot2-fire-watchdog.service\\.[A-Za-z0-9]{8}$")
        self.assertEqual(unit.stat().st_mode & 0o777, 0o600)
        self.assertEqual(stage.stat().st_mode & 0o777, 0o700)
        candidate = unit.read_text()
        self.assertIn("Restart=always", candidate)  # after operator install only
        self.assertIn("ExecStart=/usr/bin/bash " + str(self.project)
                      + "/ops/run_fire_watchdog.sh", candidate)
        self.assertEqual(
            {p.name: p.read_bytes() for p in (self.project / "data").iterdir()},
            originals
        )
        self.assertEqual(self.keys.read_text(),
                         "PRIVATE_CREDENTIAL_FILE_SHOULD_NOT_BE_OPENED\n")
        self.assertNotIn("PRIVATE_CREDENTIAL", result.stdout)

    def test_missing_original_protection_ledger_does_not_stage(self):
        (self.project / "data/fire-xaut.sqlite").unlink()
        output = self.run_installer()
        self.assertEqual(output.returncode, 2)
        self.assertIn("original existing FIRE/monitoring ledgers", output.stderr)
        self.assertFalse(
            (self.home / ".config/tradebot2/staged-units").exists()
        )
        self.assertFalse(self.external_calls.exists())

    def test_linked_key_file_and_staging_dir_are_rejected(self):
        actual = self.root / "outside-secret"
        actual.write_text("NEVER_EXPOSED")
        self.keys.unlink()
        self.keys.symlink_to(actual)
        output = self.run_installer()
        self.assertEqual(output.returncode, 2)
        self.assertFalse(self.external_calls.exists())

        self.keys.unlink()
        self.keys.write_text("SAFE_FIXTURE")
        self.keys.chmod(0o600)
        stage = self.home / ".config/tradebot2/staged-units"
        stage.symlink_to(self.root)
        output = self.run_installer()
        self.assertEqual(output.returncode, 2)
        self.assertIn("untrusted unit staging destination", output.stderr)
        self.assertFalse(self.external_calls.exists())

    def test_root_identity_fails_without_touching_anything(self):
        self.set_fake_id("0")
        output = self.run_installer()
        self.assertEqual(output.returncode, 2)
        self.assertIn("not root", output.stderr)
        self.assertFalse(self.external_calls.exists())

    def test_no_unconditional_systemd_or_source_mutations_in_script(self):
        text = SCRIPT.read_text()
        self.assertEqual(
            subprocess.run(["bash", "-n", str(SCRIPT)],
                           capture_output=True, text=True).returncode, 0)
        for forbidden in (
            "sudo ", "systemctl restart", "systemctl start",
            "systemctl enable", "systemctl daemon-reload",
            "git pull", "git switch", "git checkout",
            'mkdir -p "$PROJECT/data"', 'chmod 700 "$PROJECT/data"',
            "tradebot.fire_demo", "TRADEBOT_FIRE_DEMO_EXECUTION=true",
        ):
            self.assertNotIn(forbidden, text)
        self.assertIn("mktemp", text)
        self.assertIn('trap \'rm -f -- "$CANDIDATE"\' ERR', text)


if __name__ == "__main__":
    unittest.main()
