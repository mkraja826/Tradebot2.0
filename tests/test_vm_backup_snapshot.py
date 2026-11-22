"""Fully offline filesystem and WAL integrity tests for VM backup preflight."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tradebot.delta import DEMO_API
from tradebot.vm_backup_snapshot import MANDATORY, run_snapshot, main


def report_flat():
    return {
        "observation_status": "two_flat_snapshots_observed_not_trade_authority",
        "samples_checked": 2, "sample_interval_verified": True,
        "broker_positions_last": 0, "broker_open_orders_last": 0,
        "blockers": [], "trade_authorized": False, "order_mutations": False,
        "safe_to_enable_fire": False,
    }


class ReadOnlyBroker:
    base_url = DEMO_API
    allow_orders = False


class VmBackupTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="backup-fixtures-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.data = self.root / "original-data"
        self.backups = self.root / "private-backup"
        self.data.mkdir(mode=0o700)
        self.backups.mkdir(mode=0o700)
        for name in MANDATORY:
            source = self.data / name
            with sqlite3.connect(source) as db:
                db.execute("CREATE TABLE verified (id INTEGER PRIMARY KEY, value TEXT)")
                db.execute("INSERT INTO verified VALUES (1, ?)", (name,))
                db.commit()
            source.chmod(0o600)

    def test_preflight_default_is_no_write_no_broker(self):
        originals = {p.name: p.read_bytes() for p in self.data.iterdir()}
        def no_broker(*args, **kwargs):
            self.fail("broker request in default no-write check")
        output = run_snapshot(
            self.data, self.backups, inventory_check=no_broker)
        self.assertEqual(output["status"], "source_preflight_only")
        self.assertTrue(output["preflight_sources_verified"])
        self.assertFalse(output["backup_completed"])
        self.assertFalse(output["trade_authorized"])
        self.assertFalse(output["safe_to_deploy"])
        self.assertFalse(output["signed_two_sweep_flatness_observed"])
        self.assertEqual(list(self.backups.iterdir()), [])
        self.assertEqual(
            {p.name: p.read_bytes() for p in self.data.iterdir()}, originals)

    def test_wal_active_database_is_snapshotted_without_raw_sidecar_copy(self):
        source = self.data / "fire-ops.sqlite"
        writer = sqlite3.connect(source)
        self.addCleanup(writer.close)
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO verified VALUES(2, 'UNCOMMITTED_WAL_FIRST')")
        writer.commit()
        self.assertTrue(Path(str(source) + "-wal").exists())
        output = run_snapshot(self.data, self.backups, create=True)
        self.assertEqual(output["status"], "backup_integrity_verified")
        self.assertEqual(output["backup_file_count"], len(MANDATORY))
        self.assertFalse(output["cross_database_atomic"])
        self.assertFalse(output["safe_to_deploy"])
        backup = Path(output["snapshot_path"])
        self.assertEqual(backup.stat().st_mode & 0o777, 0o700)
        self.assertEqual(sorted(p.name for p in backup.iterdir()),
                         sorted([*MANDATORY, "manifest.json"]))
        with sqlite3.connect(backup / "fire-ops.sqlite") as db:
            self.assertEqual(db.execute(
                "SELECT count(*) FROM verified").fetchone()[0], 2)
            self.assertEqual(db.execute(
                "PRAGMA integrity_check").fetchone(), ("ok",))
        self.assertTrue(Path(str(source) + "-wal").exists())
        self.assertFalse((backup / "fire-ops.sqlite-wal").exists())
        manifest = json.loads((backup / "manifest.json").read_text())
        self.assertEqual(manifest["format"],
                         "individual_sqlite_online_backup_with_wal")
        self.assertFalse(manifest["cross_database_atomic"])
        self.assertFalse(manifest["deployment_authorized"])
        self.assertEqual(len(manifest["files"]), len(MANDATORY))
        for p in backup.iterdir():
            if p.is_file():
                self.assertEqual(p.stat().st_mode & 0o777, 0o600)

    def test_append_only_journal_is_copied_privately(self):
        journal = self.data / "trades.jsonl"
        journal.write_text('{"broker_id":"DO_NOT_PRINT"}\n')
        journal.chmod(0o600)
        out = run_snapshot(self.data, self.backups, create=True)
        self.assertTrue(out["backup_completed"])
        self.assertEqual(out["backup_file_count"], len(MANDATORY) + 1)
        copied = Path(out["snapshot_path"]) / journal.name
        self.assertEqual(copied.read_bytes(), journal.read_bytes())
        self.assertNotIn("DO_NOT_PRINT", json.dumps(out))
        self.assertEqual(copied.stat().st_mode & 0o777, 0o600)

    def test_mandatory_source_is_missing_fails_without_backup_directory(self):
        (self.data / "fire-reconciliation.sqlite").unlink()
        out = run_snapshot(self.data, self.backups, create=True)
        self.assertEqual(out["reason"], "required_private_databases_missing_or_unbounded")
        self.assertEqual(list(self.backups.iterdir()), [])
        self.assertFalse(out["backup_completed"])

    def test_refuses_symlinked_evidence_and_sidecars(self):
        source = self.data / "fire-xaut.sqlite"
        outside = self.root / "outside"
        outside.write_bytes(source.read_bytes())
        source.unlink()
        source.symlink_to(outside)
        out = run_snapshot(self.data, self.backups, create=True)
        self.assertEqual(out["reason"], "untrusted_or_permissive_source_file")
        self.assertFalse(out["backup_completed"])
        source.unlink()
        with sqlite3.connect(source) as db:
            db.execute("CREATE TABLE verified (id INTEGER PRIMARY KEY, value TEXT)")
        source.chmod(0o600)
        sidecar = self.data / "fire-xaut.sqlite-wal"
        sidecar.symlink_to(outside)
        out = run_snapshot(self.data, self.backups, create=True)
        self.assertEqual(out["reason"], "linked_sqlite_sidecar_untrusted")
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_refuses_permissive_financial_file_and_backup_root(self):
        target = self.data / "fire-equity-risk.sqlite"
        target.chmod(0o644)
        self.assertEqual(run_snapshot(
            self.data, self.backups, create=True)["reason"],
            "untrusted_or_permissive_source_file")
        target.chmod(0o600)
        self.backups.chmod(0o755)
        self.assertEqual(run_snapshot(
            self.data, self.backups, create=True)["reason"],
            "untrusted_or_permissive_directory")

    def test_original_backup_source_directory_cannot_overlap_destination(self):
        nested = self.data / "backups"
        nested.mkdir(mode=0o700)
        out = run_snapshot(self.data, nested, create=True)
        self.assertEqual(out["reason"], "backup_source_path_overlap")
        self.assertEqual(list(nested.iterdir()), [])

    def test_corrupt_database_leaves_no_claim_of_completed_backup(self):
        target = self.data / "fire-reconciliation.sqlite"
        target.write_bytes(b"NOT_A_SQLITE_DATABASE_PRIVATE")
        target.chmod(0o600)
        out = run_snapshot(self.data, self.backups, create=True)
        self.assertFalse(out["backup_completed"])
        self.assertEqual(out["reason"], "incomplete_private_backup_requires_review")
        self.assertEqual(target.read_bytes(), b"NOT_A_SQLITE_DATABASE_PRIVATE")
        self.assertFalse(any(
            x.name.startswith("snapshot-") for x in self.backups.iterdir()))

    def test_nonzero_positions_prevent_signed_precondition_and_filesystem_write(self):
        for corrupted in (
            {**report_flat(), "broker_open_orders_last": 1},
            {**report_flat(), "samples_checked": 1},
            {**report_flat(), "sample_interval_verified": False},
            {**report_flat(), "trade_authorized": True},
        ):
            called = []
            def broker_check(_ex, _root):
                called.append(True)
                return corrupted
            result = run_snapshot(
                self.data, self.backups, create=True,
                require_broker_flat=True, exchange=ReadOnlyBroker(),
                inventory_check=broker_check)
            self.assertEqual(called, [True])
            self.assertEqual(result["reason"],
                             "two_signed_flat_broker_sweeps_unverified")
            self.assertEqual(list(self.backups.iterdir()), [])

    def test_genuine_signed_two_sweep_check_is_still_not_deployment_authority(self):
        seen = []
        result = run_snapshot(
            self.data, self.backups, create=True,
            require_broker_flat=True, exchange=ReadOnlyBroker(),
            inventory_check=lambda ex, root: (
                seen.append((ex, root)), report_flat())[1])
        self.assertEqual(len(seen), 1)
        self.assertTrue(result["backup_completed"])
        self.assertTrue(result["signed_two_sweep_flatness_observed"])
        self.assertFalse(result["safe_to_deploy"])
        self.assertFalse(result["safe_to_enable_fire"])
        self.assertFalse(result["trade_authorized"])

    def test_no_private_or_live_broker_is_accepted(self):
        broker = ReadOnlyBroker()
        broker.allow_orders = True
        result = run_snapshot(
            self.data, self.backups, create=True, require_broker_flat=True,
            exchange=broker, inventory_check=lambda *_: self.fail("broker invoked"))
        self.assertEqual(result["reason"], "read_only_demo_broker_required")
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_cli_dry_run_outputs_non_authority_only(self):
        with patch("builtins.print") as printed:
            code = main(["--data-dir", str(self.data),
                         "--backup-root", str(self.backups)])
        self.assertEqual(code, 0)
        self.assertEqual(list(self.backups.iterdir()), [])
        output = " ".join(str(x) for x in printed.call_args_list)
        self.assertIn("TRADING_ENABLED: false", output)
        self.assertIn('"safe_to_deploy":false', output)
        self.assertIn('"backup_completed":false', output)
        self.assertNotIn("DO_NOT_PRINT", output)


if __name__ == "__main__":
    unittest.main()
