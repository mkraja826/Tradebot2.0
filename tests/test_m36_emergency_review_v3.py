import unittest
from unittest.mock import patch
from tradebot.m36_emergency_review_v3 import assess
from test_m27_recovery_audit_v3 import reports, NOW, S

class EmergencyReviewTests(unittest.TestCase):
    def check(self,status='flat_observed',*,halt=False,watchdog=True,receipts=0,age=0):
        a,m=reports()
        m['markets'][S]['current']['status']=status
        r=assess(S,a,m,receipts,now=NOW+age,manual_halt=halt,watchdog_healthy=watchdog)
        for key in ('execution_authorized','retry_authorized','emergency_transport_commissioned','restart_recovery_commissioned','kill_switch_commissioned'):
            self.assertIs(r[key],False)
        self.assertEqual(r['orders_submitted'],0)
        return r

    @patch('socket.socket',side_effect=AssertionError('offline only'))
    def test_flat_does_not_release(self,network):
        self.assertEqual(self.check()['disposition'],'flat_diagnostic_only')
        network.assert_not_called()

    def test_halt_and_unknown_halt(self):
        for h in (True,None,0,'false'):
            self.assertIn('manual_halt_or_unknown',self.check(halt=h)['alerts'])
            self.assertEqual(self.check(halt=h)['disposition'],'halt_and_reconcile')

    def test_watchdog_failure(self):
        for w in (False,None,1):
            self.assertIn('watchdog_unverified',self.check(watchdog=w)['alerts'])
            self.assertEqual(self.check(watchdog=w)['disposition'],'halt_and_reconcile')

    def test_unprotected_even_when_halted(self):
        r=self.check('open_protection_unverified',halt=True,watchdog=False)
        self.assertEqual(r['disposition'],'urgent_protection_review')
        self.assertIn('manual_halt_or_unknown',r['alerts'])

    def test_preserve_reported_protection(self):
        self.assertEqual(self.check('open_protection_reported',halt=True)['disposition'],'preserve_protection_and_reconcile')

    def test_flat_pending_orders(self):
        self.assertEqual(self.check('flat_orders_present')['disposition'],'reconcile_pending_orders')

    def test_unknown_stale_and_receipts(self):
        for r in (self.check('unknown'),self.check(age=91),self.check(receipts=None),self.check(receipts=1)):
            self.assertEqual(r['disposition'],'halt_and_reconcile')

    def test_invalid_input(self):
        for s,a,m in ((S,None,None),('unknown',{},{}),(S,{'markets':None},{})):
            r=assess(s,a,m,0,now=NOW,manual_halt=False,watchdog_healthy=True)
            self.assertIn('invalid_recovery_evidence',r['alerts'])
            self.assertFalse(r['execution_authorized'])
