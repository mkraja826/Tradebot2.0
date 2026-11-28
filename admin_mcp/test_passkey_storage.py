import sqlite3
import time
import unittest
from passkey_store import CredentialStore
from enrollment_store import initialize_enrollment, add_enrollment_challenge, register_verified

class StorageTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.store=CredentialStore(self.db)
        initialize_enrollment(self.db)
        self.record={"id":b"id","operator":"owner","public_key":b"fixture","sign_count":0}
        self.challenge=b"a"*32
        add_enrollment_challenge(self.db,self.challenge,"owner",int(time.time())+60)
    def test_enroll_and_replay(self):
        register_verified(self.db,self.challenge,self.record)
        self.assertEqual(self.store.lookup(b"id").operator,"owner")
        with self.assertRaises(ValueError):
            register_verified(self.db,self.challenge,self.record)
    def test_wrong_operator(self):
        with self.assertRaises(ValueError):
            register_verified(self.db,self.challenge,dict(self.record,operator="other"))
        self.assertIsNone(self.store.lookup(b"id"))
    def test_duplicate_credential_rolls_back(self):
        register_verified(self.db,self.challenge,self.record)
        challenge=b"b"*32
        add_enrollment_challenge(self.db,challenge,"owner",int(time.time())+60)
        with self.assertRaises(sqlite3.IntegrityError):
            register_verified(self.db,challenge,self.record)
        self.assertEqual(self.db.execute("SELECT count(*) FROM enrollment_challenges").fetchone()[0],1)
    def test_authentication_replay(self):
        register_verified(self.db,self.challenge,self.record)
        challenge=b"c"*32
        self.store.add_challenge(challenge,int(time.time())+60)
        self.assertTrue(self.store.consume_verified_challenge(challenge,b"id",0,1))
        self.assertFalse(self.store.consume_verified_challenge(challenge,b"id",1,2))
    def test_counter_failure_rolls_back(self):
        register_verified(self.db,self.challenge,self.record)
        challenge=b"d"*32
        self.store.add_challenge(challenge,int(time.time())+60)
        self.assertFalse(self.store.consume_verified_challenge(challenge,b"id",1,2))
        self.assertTrue(self.store.consume_verified_challenge(challenge,b"id",0,1))
