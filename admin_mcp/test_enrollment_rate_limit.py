import unittest
from enrollment_rate_limit import EnrollmentLimiter

class RateLimitTests(unittest.TestCase):
    def test_budget_and_refill(self):
        now=[0.0]
        limiter=EnrollmentLimiter(2,0.5,lambda:now[0])
        self.assertTrue(limiter.allow())
        self.assertTrue(limiter.allow())
        self.assertFalse(limiter.allow())
        now[0]=2
        self.assertTrue(limiter.allow())
        self.assertFalse(limiter.allow())
