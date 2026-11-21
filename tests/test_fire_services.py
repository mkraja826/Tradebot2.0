"""FIRE systemd scripts keep execution testnet-only and opt-in."""
from pathlib import Path
import os
import subprocess
import tempfile
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

    def test_equity_installer_refuses_staging_or_missing_original_ledger(self):
        path = ROOT / "ops/install_equity_monitor_service.sh"
        script = path.read_text()
        self.assertEqual(subprocess.run(
            ["bash", "-n", str(path)], capture_output=True
        ).returncode, 0)
        # Both currently deployed services must point to this *exact* source
        # directory before the installer writes a systemd unit. No implicit
        # switch to the isolated -review worktree is permitted.
        self.assertIn("tradebot2-dashboard.service", script)
        self.assertIn("tradebot2-fire-watchdog.service", script)
        self.assertIn('deployed_dir" != "$PROJECT"', script)
        self.assertIn('! -f "$PROJECT/data/fire-equity-risk.sqlite"', script)
        self.assertIn('tradebot.equity_install_preflight', script)
        self.assertLess(script.index('systemctl show "$service"'),
                        script.index('tradebot.equity_install_preflight'))
        self.assertLess(script.index('tradebot.equity_install_preflight'),
                        script.index('sudo install -m 0644'))
        self.assertNotIn("sudo systemctl start", script)
        self.assertNotIn("sudo systemctl enable", script)

    def test_equity_launcher_discards_inherited_old_python_package(self):
        # A protected VM keys.env may be carrying a stale PYTHONPATH.
        # Execute the launcher against a fake Python binary, not the broker.
        # Both the preflight and final daemon exec must see deployed /src.
        with tempfile.TemporaryDirectory(prefix="monitor-launch-") as tmp:
            root = Path(tmp)
            project = root / "project"
            (project / "ops").mkdir(parents=True)
            (project / ".venv/bin").mkdir(parents=True)
            (project / "src/tradebot").mkdir(parents=True)
            launcher = project / "ops/run_equity_monitor.sh"
            launcher.write_text((ROOT / "ops/run_equity_monitor.sh").read_text())

            home = root / "home"
            keys = home / ".config/tradebot2/keys.env"
            keys.parent.mkdir(parents=True)
            keys.write_text(
                "export PYTHONPATH=/tmp/old-stale-package\n"
                "export PYTHONHOME=/tmp/old-stale-home\n"
                "export PYTHONUSERBASE=/tmp/old-stale-userbase\n"
            )
            keys.chmod(0o600)

            interpreter = project / ".venv/bin/python"
            interpreter.write_text(
                "#!/usr/bin/env bash\n"
                'printf "%s|%s|%s|%s|%s\n" "$PYTHONPATH" '
                '"${PYTHONHOME:-unset}" "${PYTHONUSERBASE:-unset}" '
                '"${PYTHONSAFEPATH:-unset}" "$*" >> "$CAPTURE_FILE"\n'
            )
            interpreter.chmod(0o700)
            log = root / "capture.txt"
            proc = subprocess.run(
                ["bash", str(launcher)],
                env={**os.environ, "HOME": str(home), "CAPTURE_FILE": str(log),
                     "PYTHONPATH": "/tmp/inherited-untrusted-path"},
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            rows = [line.split("|", 4) for line in log.read_text().splitlines()]
            self.assertEqual(len(rows), 2)
            for path, pyhome, userbase, safepath, _ in rows:
                self.assertEqual(path, str(project / "src"))
                self.assertEqual(pyhome, "unset")
                self.assertEqual(userbase, "unset")
                self.assertEqual(safepath, "1")
            self.assertIn("src/tradebot/equity_monitor.py", rows[0][-1])
            self.assertIn("-m tradebot.equity_monitor", rows[1][-1])
            self.assertIn("--data-dir", rows[1][-1])

    def test_equity_monitor_guard_pins_source_and_order_safety(self):
        launcher = (ROOT / "ops/run_equity_monitor.sh").read_text()
        self.assertIn('export PYTHONPATH="$PROJECT/src"', launcher)
        self.assertLess(launcher.index('source "$KEY_FILE"'),
                        launcher.index('export PYTHONPATH="$PROJECT/src"'))
        self.assertLess(launcher.index('import tradebot.equity_monitor as monitor'),
                        launcher.index('exec "$PROJECT/.venv/bin/python" -m'))
        self.assertIn('unset PYTHONHOME PYTHONUSERBASE TB_API_KEY', launcher)
        self.assertIn('export ENABLE_DEMO_ORDERS=false', launcher)
        self.assertIn('export TRADEBOT_FIRE_DEMO_EXECUTION=false', launcher)
        self.assertIn('export TRADEBOT_GOLD_FIRE_DEMO_EXECUTION=false', launcher)

    def test_dashboard_launcher_discards_inherited_old_python_package(self):
        # A protected VM keys.env may be carrying a stale PYTHONPATH.
        # Execute the launcher against a fake Python binary, not the broker.
        # Both the preflight and final daemon exec must see deployed /src.
        with tempfile.TemporaryDirectory(prefix="dashboard-launch-") as tmp:
            root = Path(tmp)
            project = root / "project"
            (project / "ops").mkdir(parents=True)
            (project / ".venv/bin").mkdir(parents=True)
            (project / "src/tradebot").mkdir(parents=True)
            launcher = project / "ops/run_dashboard.sh"
            launcher.write_text((ROOT / "ops/run_dashboard.sh").read_text())

            home = root / "home"
            keys = home / ".config/tradebot2/keys.env"
            keys.parent.mkdir(parents=True)
            keys.write_text(
                "export PYTHONPATH=/tmp/old-stale-package\n"
                "export PYTHONHOME=/tmp/old-stale-home\n"
                "export PYTHONUSERBASE=/tmp/old-stale-userbase\n"
            )
            keys.chmod(0o600)

            interpreter = project / ".venv/bin/python"
            interpreter.write_text(
                "#!/usr/bin/env bash\n"
                'printf "%s|%s|%s|%s|%s\n" "$PYTHONPATH" '
                '"${PYTHONHOME:-unset}" "${PYTHONUSERBASE:-unset}" '
                '"${PYTHONSAFEPATH:-unset}" "$*" >> "$CAPTURE_FILE"\n'
            )
            interpreter.chmod(0o700)
            log = root / "capture.txt"
            proc = subprocess.run(
                ["bash", str(launcher)],
                env={**os.environ, "HOME": str(home), "CAPTURE_FILE": str(log),
                     "PYTHONPATH": "/tmp/inherited-untrusted-path"},
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            rows = [line.split("|", 4) for line in log.read_text().splitlines()]
            self.assertEqual(len(rows), 2)
            for path, pyhome, userbase, safepath, _ in rows:
                self.assertEqual(path, str(project / "src"))
                self.assertEqual(pyhome, "unset")
                self.assertEqual(userbase, "unset")
                self.assertEqual(safepath, "1")
            self.assertIn("src/tradebot/dashboard.py", rows[0][-1])
            self.assertIn("-m tradebot.dashboard", rows[1][-1])
            self.assertIn("--host 127.0.0.1 --port 8765", rows[1][-1])

    def test_dashboard_guard_pin_precedes_module_exec(self):
        launcher = (ROOT / "ops/run_dashboard.sh").read_text()
        self.assertIn('export PYTHONPATH="$PROJECT/src"', launcher)
        self.assertLess(launcher.index('source "$KEY_FILE"'),
                        launcher.index('export PYTHONPATH="$PROJECT/src"'))
        self.assertLess(launcher.index('import tradebot.dashboard as dashboard'),
                        launcher.index('exec "$PROJECT/.venv/bin/python" -m'))
        self.assertIn('export ENABLE_DEMO_ORDERS=false', launcher)
        self.assertIn('export TRADEBOT_DASHBOARD_DATA="$PROJECT/data"', launcher)
        self.assertIn('--host 127.0.0.1 --port 8765', launcher)

    def test_watchdog_launcher_discards_inherited_old_python_package(self):
        # A protected VM keys.env may be carrying a stale PYTHONPATH.
        # Execute the launcher against a fake Python binary, not the broker.
        # Both the preflight and final daemon exec must see deployed /src.
        with tempfile.TemporaryDirectory(prefix="watchdog-launch-") as tmp:
            root = Path(tmp)
            project = root / "project"
            (project / "ops").mkdir(parents=True)
            (project / ".venv/bin").mkdir(parents=True)
            (project / "src/tradebot").mkdir(parents=True)
            launcher = project / "ops/run_fire_watchdog.sh"
            launcher.write_text((ROOT / "ops/run_fire_watchdog.sh").read_text())

            home = root / "home"
            keys = home / ".config/tradebot2/keys.env"
            keys.parent.mkdir(parents=True)
            keys.write_text(
                "export PYTHONPATH=/tmp/old-stale-package\n"
                "export PYTHONHOME=/tmp/old-stale-home\n"
                "export PYTHONUSERBASE=/tmp/old-stale-userbase\n"
            )
            keys.chmod(0o600)

            interpreter = project / ".venv/bin/python"
            interpreter.write_text(
                "#!/usr/bin/env bash\n"
                'printf "%s|%s|%s|%s|%s\n" "$PYTHONPATH" '
                '"${PYTHONHOME:-unset}" "${PYTHONUSERBASE:-unset}" '
                '"${PYTHONSAFEPATH:-unset}" "$*" >> "$CAPTURE_FILE"\n'
            )
            interpreter.chmod(0o700)
            log = root / "capture.txt"
            proc = subprocess.run(
                ["bash", str(launcher)],
                env={**os.environ, "HOME": str(home), "CAPTURE_FILE": str(log),
                     "PYTHONPATH": "/tmp/inherited-untrusted-path"},
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            rows = [line.split("|", 4) for line in log.read_text().splitlines()]
            self.assertEqual(len(rows), 2)
            for path, pyhome, userbase, safepath, _ in rows:
                self.assertEqual(path, str(project / "src"))
                self.assertEqual(pyhome, "unset")
                self.assertEqual(userbase, "unset")
                self.assertEqual(safepath, "1")
            self.assertIn("src/tradebot/fire_watchdog.py", rows[0][-1])
            self.assertIn("-m tradebot.fire_watchdog", rows[1][-1])
            self.assertIn("--interval 15", rows[1][-1])

    def test_watchdog_import_guard_never_calls_broker(self):
        launcher = (ROOT / "ops/run_fire_watchdog.sh").read_text()
        self.assertIn('export PYTHONPATH="$PROJECT/src"', launcher)
        self.assertIn("WATCHDOG_RUNTIME_VERSION", launcher)
        self.assertIn("watchdog-telemetry-v2-20261122", launcher)
        self.assertLess(launcher.index('export PYTHONPATH="$PROJECT/src"'),
                        launcher.index('import tradebot.fire_watchdog as watchdog'))
        self.assertLess(launcher.index('import tradebot.fire_watchdog as watchdog'),
                        launcher.index('exec "$PROJECT/.venv/bin/python" -m'))

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
