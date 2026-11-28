import unittest
from unittest.mock import patch, mock_open
import json
import time
import stat
from types import SimpleNamespace
from admin_mcp import tb2_admin as admin

class AdminV2Tests(unittest.TestCase):
    def test_registration(self):
        report = admin.admin_capabilities()
        self.assertIn("gold_v2_qa_report", report["tools"])
        self.assertEqual(report["tool_count"], 23)
        self.assertFalse(report["remote_execution"])

    def test_journal_failure(self):
        with patch.object(admin, "SERVICES", ("test.service",)), patch.object(admin, "command", return_value={"exit_code":1,"stdout":"","stderr":"Permission denied"}):
            result = admin.service_diagnostics("test.service")
        self.assertEqual(result["journal_status"], "permission_limited")
        self.assertIsNone(result["counts"])

    def test_missing_export(self):
        with patch.object(admin.os, "open", side_effect=FileNotFoundError):
            self.assertEqual(admin.gold_v2_qa_report()["status"], "export_not_configured")

    def test_scan_freshness(self):
        now = time.time()
        raw = json.dumps({"schema_version":1,"scans":[{"timestamp":now-15,"conditions":{"trend":True}},{"timestamp":now,"conditions":{"trend":False,"ignored":"text"}}]}).encode()
        with patch.object(admin.os,"open",return_value=99), patch.object(admin.os,"fdopen",mock_open(read_data=raw)), patch.object(admin.os,"fstat",return_value=SimpleNamespace(st_mode=stat.S_IFREG)):
            report = admin.gold_v2_qa_report()
        self.assertEqual(report["status"],"fresh")
        self.assertEqual(report["largest_observed_gap_seconds"],15)
        self.assertEqual(report["scans"][-1]["conditions"],{"trend":False})

if __name__ == "__main__":
    unittest.main()
