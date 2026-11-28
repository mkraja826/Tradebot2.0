import base64
import sqlite3
import unittest
from unittest.mock import patch
import provisioning_session as sessions
import enrollment_session_binding as binding
import enrollment_atomic as atomic

class EnrollmentSecurity(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute("CREATE TABLE credentials(id BLOB PRIMARY KEY, operator TEXT, public_key BLOB, sign_count INTEGER)")
        sessions.initialize(self.db)
        binding.initialize(self.db)
        self.policy = {"rp_id":"tradingbot.micirql.com","origin":"https://tradingbot.micirql.com","operators":["alice","bob"],"provisioning_admins":["admin"]}
        self.token = sessions.issue(self.db,"admin",self.policy,"alice")
        self.challenge = self.options(self.token)
    def tearDown(self):
        self.db.close()
    def options(self, token):
        return base64.urlsafe_b64decode(binding.options(self.db,self.policy,token,"alice")["challenge"]+"=")
    def finish(self, token=None, operator="alice", challenge=None):
        return atomic.complete(self.db,self.policy,token or self.token,operator,challenge or self.challenge,"{}")
    def test_unauthorized_admin(self):
        with self.assertRaises(PermissionError):
            sessions.issue(self.db,"unknown",self.policy,"alice")
    def test_operator_bound_options(self):
        with self.assertRaises(PermissionError):
            binding.options(self.db,self.policy,self.token,"bob")
    def test_expired_token(self):
        with self.db:
            self.db.execute("UPDATE provisioning_sessions SET expires=0")
        with self.assertRaises(PermissionError):
            self.finish()
    def test_wrong_operator(self):
        with self.assertRaises(PermissionError):
            self.finish(operator="bob")
    def test_cross_session(self):
        other = sessions.issue(self.db,"admin",self.policy,"alice")
        self.options(other)
        with self.assertRaises(ValueError):
            self.finish(token=other)
    def test_replaced_challenge(self):
        self.options(self.token)
        with self.assertRaises(ValueError):
            self.finish()
    def test_wrong_origin(self):
        self.policy["origin"]="https://example.org"
        with self.assertRaises(ValueError):
            self.finish()
    @patch("enrollment_atomic.verify_enrollment")
    def test_success_and_replay(self, verify):
        verify.return_value={"id":b"id","operator":"alice","public_key":b"key","sign_count":0}
        self.assertEqual(self.finish(),b"id")
        self.assertIsNone(sessions.authenticate(self.db,self.token))
        with self.assertRaises(PermissionError):
            self.finish()
        self.assertEqual(self.db.execute("SELECT count(*) FROM credentials").fetchone()[0],1)
    @patch("enrollment_atomic.verify_enrollment")
    def test_rollback(self, verify):
        verify.return_value={"id":b"id","operator":"alice","public_key":b"key","sign_count":0}
        with self.db:
            self.db.execute("INSERT INTO credentials VALUES (?,?,?,?)",(b"id","alice",b"key",0))
        with self.assertRaises(sqlite3.IntegrityError):
            self.finish()
        self.assertEqual(sessions.authenticate(self.db,self.token),"admin")
        self.assertEqual(self.db.execute("SELECT count(*) FROM bound_enrollment").fetchone()[0],1)

if __name__ == "__main__":
    unittest.main()
