import concurrent.futures
import threading
import unittest
from unittest.mock import patch
from test_enrollment_web import EnrollmentWebTests

class ConcurrentEnrollment(unittest.TestCase):
    def test_single_winner(self):
        fixture = EnrollmentWebTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        status, _, options = fixture.request()
        self.assertEqual(status, "200 OK")
        body = {"operator":"alice","challenge":options["challenge"],"response":"{}"}
        barrier = threading.Barrier(2)
        def submit():
            barrier.wait(timeout=5)
            return fixture.request("complete",body)[0]
        with patch("enrollment_atomic.verify_enrollment",return_value={"id":b"id","operator":"alice","public_key":b"key","sign_count":0}) as verify:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _:submit(),range(2)))
            self.assertCountEqual(results,["200 OK","403 Forbidden"])
            self.assertEqual(verify.call_count,1)
        db = fixture.connect()
        try:
            self.assertEqual(db.execute("SELECT count(*) FROM credentials").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT count(*) FROM provisioning_sessions").fetchone()[0],0)
        finally:
            db.close()
