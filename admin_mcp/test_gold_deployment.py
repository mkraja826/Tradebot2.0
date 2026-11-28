import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import gold_deployment_worker as worker
from approval_ledger import initialize
from execution_journal import initialize_journal
from gold_deployment import AUDIENCE, GoldDeploymentAPI, initialize as initialize_gold
from operator_auth import issue_after_verification


class GoldTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        initialize(self.db)
        initialize_journal(self.db)
        initialize_gold(self.db)
        self.key = b"k" * 32
        self.rid, self.old, self.new = "a"*32, "b"*40, "c"*40
        self.record = {"id": self.rid, "action": "deploy_version", "status": "pending_local_approval",
                       "arguments": {"commit_sha": self.new}}
        self.policy = {"operators": ["owner"], "audience": AUDIENCE}
        self.api = GoldDeploymentAPI(lambda _: self.record, lambda: (self.old, self.new), None,
                                     self.policy, self.key, self.db, lambda: 1001)
        self.request = self.api.request(self.rid)
        self.envelope = issue_after_verification(self.request, "a"*64, "assertion", lambda *a: "owner",
                                                 self.policy, self.key, 1000)
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for revision in (self.old, self.new):
            (self.root/"releases"/revision).mkdir(parents=True)
        self.current = self.root/"current"
        self.current.symlink_to(self.root/"releases"/self.old)
        patcher = patch.object(worker, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_activate_once(self):
        self.api.reserve(self.request, self.envelope)
        with patch.object(worker, "restart_and_verify") as check:
            self.assertEqual(worker.run_reserved(self.db, self.rid)["status"], "succeeded")
            check.assert_called_once_with(self.current.resolve())
            self.assertEqual(self.current.resolve().name, self.new)
            with self.assertRaises(ValueError):
                worker.run_reserved(self.db, self.rid)

    def test_rollback(self):
        self.api.reserve(self.request, self.envelope)
        with patch.object(worker, "restart_and_verify", side_effect=[RuntimeError(), None]):
            self.assertEqual(worker.run_reserved(self.db, self.rid)["status"], "failed")
        self.assertEqual(self.current.resolve().name, self.old)

    def test_failed_rollback_retains_lock(self):
        self.api.reserve(self.request, self.envelope)
        with patch.object(worker, "restart_and_verify", side_effect=RuntimeError), self.assertRaises(RuntimeError):
            worker.run_reserved(self.db, self.rid)
        self.assertEqual(self.db.execute("SELECT status FROM executions").fetchone()[0], "unknown")

    def test_unapproved_request(self):
        with self.assertRaises(ValueError):
            worker.run_reserved(self.db, self.rid)

    def test_staged_revision_changed(self):
        self.api.release_state = lambda: (self.old, "d"*40)
        with self.assertRaises(ValueError):
            self.api.reserve(self.request, self.envelope)

    def test_duplicate_approval(self):
        self.api.reserve(self.request, self.envelope)
        with self.assertRaises(sqlite3.IntegrityError):
            self.api.reserve(self.request, self.envelope)
