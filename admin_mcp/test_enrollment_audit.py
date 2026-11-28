import unittest
import test_enrollment_web as fixtures

class EnrollmentAuditTests(unittest.TestCase):
    def test_audit_excludes_secrets(self):
        fixture=fixtures.EnrollmentWebTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        with self.assertLogs("recover.enrollment.audit",level="INFO") as logs:
            self.assertEqual(fixture.request()[0],"200 OK")
            self.assertEqual(fixture.request(HTTP_AUTHORIZATION="Bearer "+"0"*64)[0],"403 Forbidden")
        output=" ".join(logs.output)
        self.assertIn("action=options status=200",output)
        self.assertIn("action=options status=403",output)
        self.assertNotIn(fixture.token,output)
        self.assertNotIn("0"*64,output)
        self.assertNotIn("alice",output)
