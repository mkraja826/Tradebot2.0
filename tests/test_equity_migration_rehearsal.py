"""Offline only: additive equity schema rehearsal must preserve original history."""
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest

from tradebot.equity_migration_rehearsal import rehearse_backup_migration


class EquityMigrationRehearsalTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "tradebot-backups"
        self.root.mkdir()
        self.source_dir = self.root / "full-20261121T140000Z"
        self.source_dir.mkdir()
        self.db_path = self.source_dir / "fire-equity-risk.sqlite"

    def legacy(self, *, peak="1500"):
        with sqlite3.connect(self.db_path) as db:
            db.executescript("""
                CREATE TABLE equity_evidence(
                    observed_us INTEGER PRIMARY KEY,
                    equity_usd TEXT NOT NULL,
                    origin TEXT NOT NULL);
                CREATE TABLE equity_watermark(
                    singleton INTEGER PRIMARY KEY,
                    high_usd TEXT NOT NULL);
                INSERT INTO equity_evidence VALUES
                    (1795200000000000, '1000', 'delta_demo_signed_wallet');
                INSERT INTO equity_evidence VALUES
                    (1795286400000000, '1500', 'delta_demo_signed_wallet');
            """)
            db.execute("INSERT INTO equity_watermark VALUES(1,?)", (peak,))
        return self.db_path.read_bytes()

    def check(self):
        return rehearse_backup_migration(self.source_dir, backup_root=self.root)

    def test_legacy_migration_preserves_source_rows_watermark_and_zero_receipts(self):
        original_bytes = self.legacy()
        result = self.check()
        self.assertEqual(result["status"],
                         "copy_migration_rehearsal_passed_not_release_authority")
        for field in ("backup_unmodified", "historical_observations_preserved",
                      "peak_watermark_preserved", "historical_receipts_preserved",
                      "migrated_copy_schema_ready"):
            self.assertIs(result[field], True, field)
        for field in ("fabricated_receipts", "trade_authorized",
                      "safe_to_enable_fire", "active_database_mutations",
                      "active_service_mutations", "broker_order_mutations"):
            self.assertIs(result[field], False, field)
        self.assertEqual(self.db_path.read_bytes(), original_bytes)
        with sqlite3.connect(self.db_path) as original:
            self.assertIsNone(original.execute(
                "SELECT name FROM sqlite_master "
                "WHERE name='equity_read_receipts'").fetchone())
        output = Path(result["drill_location"]) / "fire-equity-risk.sqlite"
        self.assertTrue(output.is_file())
        with sqlite3.connect(output) as copy:
            self.assertEqual(copy.execute(
                "SELECT COUNT(*) FROM equity_evidence").fetchone()[0], 2)
            self.assertEqual(copy.execute(
                "SELECT high_usd FROM equity_watermark").fetchone()[0], "1500")
            self.assertEqual(copy.execute(
                "SELECT COUNT(*) FROM equity_read_receipts").fetchone()[0], 0)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_original_immutable_backup_file_is_never_changed(self):
        self.legacy()
        original = self.db_path.read_bytes()
        first = self.check()
        second = self.check()
        self.assertEqual(first["reason"], "none")
        self.assertEqual(second["reason"], "none")
        self.assertNotEqual(first["drill_location"], second["drill_location"])
        self.assertEqual(self.db_path.read_bytes(), original)

    def test_missing_snapshot_is_refused_without_creating_database(self):
        result = self.check()
        self.assertEqual(result["reason"], "trusted_backup_unavailable")
        self.assertIsNone(result["drill_location"])
        self.assertFalse(self.db_path.exists())

    def test_backup_outside_private_full_directory_is_refused(self):
        self.legacy()
        other = self.root / "runtime-20261121T140000Z"
        other.mkdir()
        (other / "fire-equity-risk.sqlite").write_bytes(
            self.db_path.read_bytes())
        result = rehearse_backup_migration(other, backup_root=self.root)
        self.assertEqual(result["reason"], "trusted_backup_unavailable")
        self.assertIsNone(result["drill_location"])

    def test_symlinked_backup_is_refused(self):
        self.legacy()
        second = self.source_dir / "backup-original.sqlite"
        self.db_path.rename(second)
        self.db_path.symlink_to(second)
        result = self.check()
        self.assertEqual(result["reason"], "trusted_backup_unavailable")
        self.assertIsNone(result["drill_location"])

    def test_corrupt_snapshot_refused_without_repair(self):
        self.db_path.write_bytes(b"not-valid-sqlite")
        before = self.db_path.read_bytes()
        result = self.check()
        self.assertEqual(result["reason"], "copy_migration_unverified")
        self.assertEqual(self.db_path.read_bytes(), before)
        self.assertFalse(result["trade_authorized"])

    def test_lowered_historical_high_watermark_refused_without_reset(self):
        original_bytes = self.legacy(peak="100")
        result = self.check()
        self.assertEqual(result["reason"], "copy_migration_unverified")
        self.assertFalse(result["migrated_copy_schema_ready"])
        self.assertEqual(self.db_path.read_bytes(), original_bytes)
        self.assertFalse(result["safe_to_enable_fire"])


if __name__ == "__main__":
    unittest.main()
