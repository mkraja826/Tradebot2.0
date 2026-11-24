"""Offline independent backup checks and isolated restore, never live VM writes."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from tradebot.vm_backup_snapshot import MANDATORY, run_snapshot
from tradebot.vm_backup_restore_check import verify_snapshot, main


class VerifySnapshotTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory(prefix="restore-tests-")
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.data = self.root / "live"
        self.backups = self.root / "private-backups"
        self.rehearsal = self.root / "isolated-rehearsal"
        for folder in (self.data, self.backups, self.rehearsal):
            folder.mkdir(mode=0o700)
        for name in MANDATORY:
            with sqlite3.connect(self.data / name) as db:
                db.execute("CREATE TABLE original (id INTEGER PRIMARY KEY, value TEXT)")
                db.execute("INSERT INTO original VALUES (1,?)", (name,))
            (self.data / name).chmod(0o600)
        self.secret = "PRIVATE_BROKER_IDENTIFIER_DO_NOT_LOG"
        (self.data / "private.jsonl").write_text(
            json.dumps({"trade": self.secret}) + "\n")
        (self.data / "private.jsonl").chmod(0o600)
        snap = run_snapshot(self.data, self.backups, create=True)
        self.assertEqual(snap["status"], "backup_integrity_verified")
        self.snapshot = Path(snap["snapshot_path"])

    def snapshot_bytes(self):
        return {p.name: p.read_bytes()
                for p in self.snapshot.iterdir() if p.is_file()}

    def test_manifest_and_all_db_checks_without_writing_files(self):
        before = self.snapshot_bytes()
        source_before = {p.name:p.read_bytes() for p in self.data.iterdir()}
        result = verify_snapshot(self.snapshot)
        self.assertEqual(result["status"], "backup_independently_verified")
        self.assertTrue(result["checksums_verified"])
        self.assertTrue(result["standalone_sqlite_integrity_verified"])
        self.assertFalse(result["isolated_restore_exercised"])
        self.assertFalse(result["trade_authorized"])
        self.assertFalse(result["safe_to_deploy"])
        self.assertFalse(result["safe_to_enable_fire"])
        self.assertFalse(result["cross_database_atomic"])
        self.assertEqual(result["files_verified"], len(MANDATORY) + 1)
        self.assertEqual(before, self.snapshot_bytes())
        self.assertEqual(source_before, {
            p.name:p.read_bytes() for p in self.data.iterdir()})
        self.assertEqual(list(self.rehearsal.iterdir()), [])
        self.assertNotIn(self.secret, json.dumps(result))

    def test_wal_committed_data_survives_full_isolated_rehearsal(self):
        # Source has a live committed WAL change at backup time.
        writer = sqlite3.connect(self.data / "fire-ops.sqlite")
        self.addCleanup(writer.close)
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO original VALUES (2,'WAL_COMMITTED')")
        writer.commit()
        second = run_snapshot(self.data, self.backups, create=True)
        self.assertTrue(second["backup_completed"])
        saved = Path(second["snapshot_path"])
        with sqlite3.connect(saved / "fire-ops.sqlite") as db:
            self.assertEqual(db.execute(
                "SELECT count(*) FROM original").fetchone()[0], 2)
        before = {p.name:p.read_bytes() for p in saved.iterdir()}
        result = verify_snapshot(saved, rehearsal_root=self.rehearsal)
        self.assertEqual(result["status"], "backup_independently_verified")
        self.assertTrue(result["isolated_restore_exercised"])
        self.assertEqual(list(self.rehearsal.iterdir()), [])
        self.assertEqual(before, {p.name:p.read_bytes() for p in saved.iterdir()})
        self.assertTrue(Path(str(self.data / "fire-ops.sqlite") + "-wal").exists())

    def test_corrupt_backup_is_detected_without_mutating_it(self):
        db = self.snapshot / "fire-ops.sqlite"
        with db.open("ab") as stream:
            stream.write(b"PRIVATE_CORRUPTION")
        before = db.read_bytes()
        report = verify_snapshot(self.snapshot, rehearsal_root=self.rehearsal)
        self.assertEqual(report["reason"], "snapshot_file_checksum_mismatch")
        self.assertFalse(report["isolated_restore_exercised"])
        self.assertEqual(db.read_bytes(), before)
        self.assertEqual(list(self.rehearsal.iterdir()), [])

    def test_missing_file_rejects_snapshot(self):
        (self.snapshot / "fire-reconciliation.sqlite").unlink()
        report = verify_snapshot(self.snapshot)
        self.assertEqual(report["reason"], "snapshot_contains_unaccounted_files")
        self.assertFalse(report["manifest_verified"])

    def test_extra_wal_or_secret_file_or_nested_directory_fails(self):
        for file, is_directory in (
            ("fire-ops.sqlite-wal", False),
            ("secrets.env", False),
            ("nested-private-data", True),
        ):
            with self.subTest(file=file):
                extra = self.snapshot / file
                if is_directory:
                    extra.mkdir(mode=0o700)
                else:
                    extra.write_bytes(b"SECRET")
                    extra.chmod(0o600)
                self.assertEqual(
                    verify_snapshot(self.snapshot)["reason"],
                    "snapshot_contains_unaccounted_files")
                if is_directory:
                    extra.rmdir()
                else:
                    extra.unlink()

    def test_path_traversal_and_duplicate_manifest_entry_rejected(self):
        file = self.snapshot / "manifest.json"
        doc = json.loads(file.read_text())
        doc["files"][0]["file"] = "../original-data/fire-ops.sqlite"
        file.write_text(json.dumps(doc))
        file.chmod(0o600)
        result = verify_snapshot(self.snapshot)
        self.assertEqual(result["reason"], "snapshot_manifest_entry_invalid")
        self.assertFalse(result["checksums_verified"])

    def test_duplicate_json_keys_and_extra_authority_field_rejected(self):
        file = self.snapshot / "manifest.json"
        original = file.read_text()
        file.write_text(original.replace('"version":1', '"version":1,"version":1'))
        file.chmod(0o600)
        self.assertEqual(
            verify_snapshot(self.snapshot)["reason"],
            "duplicate_manifest_fields")
        file.write_text(original.replace(
            '"deployment_authorized":false',
            '"deployment_authorized":false,"trade_authorized":true'))
        file.chmod(0o600)
        self.assertEqual(
            verify_snapshot(self.snapshot)["reason"],
            "snapshot_manifest_structure_unverified")

    def test_forged_success_flag_or_not_atomic_claim_is_rejected(self):
        file = self.snapshot / "manifest.json"
        original = json.loads(file.read_text())
        for field in ("deployment_authorized", "cross_database_atomic",
                      "broker_order_mutations"):
            with self.subTest(field=field):
                doc = {**original, field:True}
                file.write_text(json.dumps(doc))
                file.chmod(0o600)
                self.assertEqual(
                    verify_snapshot(self.snapshot)["reason"],
                    "snapshot_manifest_safety_flags_invalid")

    def test_snapshot_symlink_to_original_data_is_rejected(self):
        alias = self.root / "snapshot-12345678"
        alias.symlink_to(self.snapshot, target_is_directory=True)
        self.assertEqual(
            verify_snapshot(alias)["reason"],
            "untrusted_or_permissive_directory")
        self.assertFalse(verify_snapshot(alias)["safe_to_deploy"])

    def test_rehearsal_cannot_overlap_snapshot_or_be_symlinked(self):
        report = verify_snapshot(self.snapshot, rehearsal_root=self.snapshot)
        self.assertEqual(report["reason"], "restore_destination_overlaps_snapshot")
        self.assertEqual(list(self.rehearsal.iterdir()), [])
        symlink = self.root / "rehearsal-alias"
        symlink.symlink_to(self.rehearsal, target_is_directory=True)
        self.assertEqual(
            verify_snapshot(self.snapshot, rehearsal_root=symlink)["reason"],
            "untrusted_or_permissive_directory")

    def test_incomplete_backup_folder_is_not_a_restorable_snapshot(self):
        fake = self.backups / ".incomplete-snapshot-12345678"
        fake.mkdir(mode=0o700)
        self.assertEqual(
            verify_snapshot(fake)["reason"],
            "completed_snapshot_name_unverified")

    def test_cli_reports_only_boolean_evidence_never_secrets(self):
        with patch("builtins.print") as printer:
            self.assertEqual(main(["--snapshot", str(self.snapshot)]), 0)
        printed = " ".join(str(v) for v in printer.call_args_list)
        self.assertIn("TRADING_ENABLED: false", printed)
        self.assertIn('"safe_to_deploy":false', printed)
        self.assertNotIn(self.secret, printed)
        self.assertNotIn(str(self.snapshot), printed)


if __name__ == "__main__":
    unittest.main()
