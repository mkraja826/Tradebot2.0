"""No-network two-sweep account flatness and nonauthorization tests."""
import unittest
from tradebot.delta import DeltaDemo
from tradebot.btc_readonly_account_sweep import observe_flat_twice

def flat():
    return {
        "status":"signed_exposure_snapshot_observed",
        "blocker":"none_in_this_single_snapshot",
        "account_wide_margined_positions_nonzero":0,
        "account_wide_open_or_pending_orders":0,
        "realtime_fire_position_sizes":{"BTCUSD":"0","XAUTUSD":"0"},
        "margined_realtime_consistent":True,
        "any_exposure_observed":False
    }

class DoubleSweepTests(unittest.TestCase):
    def check(self, *, samples=None, modes=None, spacing=11):
        sampled = list(samples or [flat(),flat()])
        modes = list(modes or [(501,None),(501,None)])
        stamps = iter([0,spacing])
        count = []
        def sample(_):
            count.append("sample")
            return sampled.pop(0)
        def identify(_):
            count.append("identity")
            return modes.pop(0)
        result = observe_flat_twice(
            DeltaDemo(),sample=sample,identify=identify,
            pause=lambda s:count.append("pause"),
            monotonic=lambda:next(stamps))
        return result,count

    def test_two_separate_flat_samples_with_stable_account(self):
        r,calls=self.check()
        self.assertEqual(r["status"],"two_signed_flat_snapshots_not_release_authority")
        self.assertTrue(r["two_sample_flatness_observed"])
        self.assertTrue(r["main_account_identity_stable"])
        self.assertFalse(r["broker_margin_verified"])
        self.assertFalse(r["trade_authorized"])
        self.assertFalse(r["safe_to_enable_fire"])
        self.assertEqual(calls,["identity","sample","pause","sample","identity"])

    def test_second_snapshot_exposure_rejected(self):
        exposed=flat()
        exposed["account_wide_open_or_pending_orders"]=1
        r,_=self.check(samples=[flat(),exposed])
        self.assertEqual(r["reason"],"second_account_exposure_unverified")
        self.assertFalse(r["two_sample_flatness_observed"])

    def test_insufficient_spacing_rejected(self):
        r,_=self.check(spacing=1)
        self.assertEqual(r["reason"],"sample_spacing_unverified")
        self.assertFalse(r["two_sample_flatness_observed"])

    def test_identity_changes_rejected(self):
        r,_=self.check(modes=[(501,None),(999,None)])
        self.assertEqual(r["reason"],"signed_account_identity_changed")

    def test_contradictory_margin_proof_rejected(self):
        r,_=self.check(modes=[(501,"portfolio"),(501,"portfolio")])
        self.assertEqual(r["reason"],"signed_margin_mode_contradicts_owner")
        self.assertFalse(r["two_sample_flatness_observed"])
