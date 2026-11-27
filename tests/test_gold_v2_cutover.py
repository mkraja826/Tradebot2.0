import unittest
from recover_trading.gold_v2_cutover import assess

class CutoverTests(unittest.TestCase):
    def test_missing_evidence(self):
        r=assess({})
        self.assertFalse(r["activation_ready"])
        self.assertEqual(r["execution_effect"],"none")
        self.assertIn("running_revision",r["unverified_checks"])
    def test_shared_process(self):
        r=assess({"legacy_gold_process_scope":"btc_and_gold"})
        self.assertIn("isolated_gold_process",r["unverified_checks"])
    def test_revision_binding(self):
        r=assess({"candidate_sha":"a"*40,"ci_passed_sha":"b"*40})
        self.assertIn("candidate_revision",r["unverified_checks"])
    def test_matching_ci(self):
        r=assess({"candidate_sha":"a"*40,"ci_passed_sha":"a"*40})
        self.assertEqual(r["operator_reported_checks"]["candidate_revision"],"reported_ready")
        self.assertFalse(r["activation_ready"])
    def test_operator_flags_cannot_override_engineering(self):
        r=assess({"activation_ready":True,"exclusive_gold_owner_verified":True})
        self.assertFalse(r["activation_ready"])
        self.assertIn("execution_runtime_integration_unverified",r["engineering_blockers"])
    def test_invalid_manifest(self):
        with self.assertRaises(ValueError):assess([])
