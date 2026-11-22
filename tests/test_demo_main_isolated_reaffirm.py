"""Offline no-trade verification of one-time DEMO Main margin confirmation."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tradebot.delta import DEMO_API, DeltaDemo
from tradebot.fire_account_guard import (
    AccountExposureRejected, require_flat_demo_account,
    require_flat_demo_account_for_configuration,
)
from tradebot.demo_main_isolated_reaffirm import (
    APPROVAL, MARKER, AccountSettingRejected,
    IsolatedOnlyDeltaMutation, reaffirm_main_demo,
)


class FlatDemoBroker:
    base_url = DEMO_API
    allow_orders = False

    def __init__(self, *, positions=None, orders=None, after=None,
                 first_uid=501, second_uid=501, account_name=None):
        self.calls = []
        self.positions = positions if positions is not None else []
        self.orders = orders if orders is not None else []
        self.after = after
        self.user_ids = [first_uid, second_uid]
        self.account_name = account_name
        self.pref_calls = 0

    def _request(self, method, path, *, params=None, auth=False, **kwargs):
        self.calls.append((method, path, auth))
        assert method == "GET"
        if path == "/v2/users/trading_preferences":
            uid = self.user_ids[min(self.pref_calls, len(self.user_ids)-1)]
            self.pref_calls += 1
            return {"result": {"user_id": uid,
                               **({"account_name": self.account_name}
                                  if self.account_name is not None else {})}}
        if path == "/v2/positions/margined":
            return {"result": self.positions}
        if path == "/v2/orders":
            return {"result": self.orders, "meta": {"after": self.after}}
        if path in ("/v2/products/BTCUSD", "/v2/products/XAUTUSD"):
            symbol = path.rsplit("/",1)[-1]
            return {"result": {
                "symbol": symbol, "contract_type": "perpetual_futures",
                "id": 101 if symbol == "BTCUSD" else 102}}
        if path == "/v2/positions":
            assert params and params.get("product_id") in (101,102)
            return {"result": [], "meta": {"after": None}}
        raise AssertionError("Unexpected signed API path")

    def __init_subclass__(cls):
        pass


class FakeMainDemoFactory:
    def __init__(self, **kwargs):
        self.broker = FlatDemoBroker()

    def __call__(self, **kwargs):
        return self.broker


class MutationRecorder:
    calls = []

    def __init__(self, api_key, api_secret):
        self.base_url = DEMO_API

    def reaffirm_isolated(self, user):
        self.calls.append(user)
        return True


class ReaffirmationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.client = FlatDemoBroker()
        MutationRecorder.calls = []

    def run_attempt(self, *, execute=False, approval=None,
                    client=None, services=lambda:True,
                    disabled=lambda:True,
                    mutate=MutationRecorder):
        broker = client or self.client
        def factory(**kwargs):
            return broker
        times = iter([100.0, 111.5])
        return reaffirm_main_demo(
            self.root, execute=execute, approval=approval,
            broker_factory=factory, mutation_factory=mutate,
            services=services, fire_disabled=disabled,
            pause=lambda seconds: None, monotonic=lambda: next(times),
        )

    def test_readonly_preflight_no_marker_and_all_authenticated_gets(self):
        outcome = self.run_attempt()
        self.assertEqual(outcome["status"],
                         "awaiting_one_time_operator_confirmation")
        self.assertTrue(outcome["account_wide_flat_twice"])
        self.assertFalse(outcome["trading_enabled"])
        self.assertFalse(outcome["broker_orders_submitted"])
        self.assertFalse((self.root / MARKER).exists())
        self.assertEqual(MutationRecorder.calls, [])
        self.assertTrue(all(method == "GET" for method,_,_ in self.client.calls))
        self.assertEqual(self.client.pref_calls, 2)

    def test_execute_approved_creates_marker_before_single_put(self):
        class MarkerGuard(MutationRecorder):
            def reaffirm_isolated(inner, user):
                self.assertTrue((self.root / MARKER).exists())
                return super().reaffirm_isolated(user)
        result = self.run_attempt(
            execute=True, approval=APPROVAL, mutate=MarkerGuard)
        self.assertEqual(result["status"],
                         "isolated_setting_acknowledged_readback_absent")
        self.assertTrue(result["isolated_setting_acknowledged"])
        self.assertFalse(result["post_change_readback_isolated"])
        self.assertTrue(result["one_time_marker_consumed"])
        self.assertEqual(MutationRecorder.calls, ["501"])
        self.assertFalse(result["trading_enabled"])
        self.assertFalse(result["broker_orders_submitted"])
        self.assertEqual((self.root / MARKER).stat().st_mode & 0o777, 0o600)
        repeat = self.run_attempt(execute=True, approval=APPROVAL)
        self.assertEqual(repeat["blockers"],
                         ["main_margin_reaffirm_already_attempted"])
        self.assertEqual(MutationRecorder.calls, ["501"])

    def test_wrong_approval_fails_without_marker(self):
        result=self.run_attempt(execute=True, approval="NO")
        self.assertEqual(result["blockers"], ["operator_confirmation_required"])
        self.assertFalse((self.root / MARKER).exists())

    def test_active_positions_block_before_setting(self):
        client=FlatDemoBroker(
            positions=[{"product_id": 101, "size": 1}])
        result=self.run_attempt(
            execute=True, approval=APPROVAL, client=client)
        self.assertEqual(result["blockers"],
                         ["account_identity_or_exposure_unverified"])
        self.assertFalse((self.root / MARKER).exists())

    def test_any_open_order_blocks_without_setting(self):
        client=FlatDemoBroker(
            orders=[{"id": 82, "product_id": 114}])
        result=self.run_attempt(
            execute=True, approval=APPROVAL, client=client)
        self.assertEqual(result["blockers"],
                         ["account_identity_or_exposure_unverified"])
        self.assertFalse((self.root / MARKER).exists())

    def test_unverified_order_pagination_blocks(self):
        client=FlatDemoBroker(after="another-page")
        result=self.run_attempt(
            execute=True, approval=APPROVAL, client=client)
        self.assertEqual(result["blockers"],
                         ["account_identity_or_exposure_unverified"])
        self.assertEqual(MutationRecorder.calls, [])

    def test_second_signed_identity_changed(self):
        client=FlatDemoBroker(first_uid=501, second_uid=502)
        result=self.run_attempt(execute=True, approval=APPROVAL,client=client)
        self.assertEqual(result["blockers"],
                         ["account_identity_or_exposure_unverified"])
        self.assertEqual(MutationRecorder.calls, [])

    def test_main_scope_contradiction_fails(self):
        client=FlatDemoBroker(account_name="Other")
        result=self.run_attempt(execute=True, approval=APPROVAL,client=client)
        self.assertEqual(result["blockers"],
                         ["account_identity_or_exposure_unverified"])
        self.assertEqual(MutationRecorder.calls, [])

    def test_watchdog_or_disabled_fire_required(self):
        for services,disabled in ((lambda:False,lambda:True),
                                  (lambda:True,lambda:False)):
            with self.subTest(services=services(),disabled=disabled()):
                result = self.run_attempt(
                    execute=True, approval=APPROVAL, services=services,
                    disabled=disabled)
                self.assertFalse(result["account_wide_flat_twice"])
                self.assertFalse((self.root / MARKER).exists())

    def test_mutation_unknown_result_consumes_marker_without_retry(self):
        class UncertainMutation(MutationRecorder):
            def reaffirm_isolated(self, user):
                raise RuntimeError("provider-timeout: no retry")
        result=self.run_attempt(
            execute=True,approval=APPROVAL,mutate=UncertainMutation)
        self.assertEqual(result["blockers"], ["account_setting_outcome_uncertain"])
        self.assertTrue(result["one_time_marker_consumed"])
        repeat=self.run_attempt(execute=True,approval=APPROVAL)
        self.assertEqual(repeat["blockers"],
                         ["main_margin_reaffirm_already_attempted"])

    def test_actual_client_only_allows_one_expected_put_and_no_orders(self):
        client=IsolatedOnlyDeltaMutation("dummy","dummy")
        with self.assertRaises(AccountSettingRejected):
            client._request("POST", "/v2/orders", auth=True,
                            payload={"product_id":123})
        with self.assertRaises(AccountSettingRejected):
            client._request("DELETE", "/v2/orders/all", auth=True)
        with self.assertRaises(AccountSettingRejected):
            client._request("PUT", "/v2/users/margin_mode", auth=True,
                            payload={"margin_mode":"portfolio",
                                     "subaccount_user_id":"501"})
        with patch.object(DeltaDemo, "_request", return_value={
            "success":True,
            "result":{"id":"501","margin_mode":"isolated"}}) as call:
            self.assertTrue(client.reaffirm_isolated("501"))
            self.assertEqual(call.call_count,1)
            args, kwargs = call.call_args
            self.assertEqual(args[0:2],
                             ("PUT", "/v2/users/margin_mode"))
            self.assertEqual(kwargs["payload"],
                             {"margin_mode":"isolated",
                              "subaccount_user_id":"501"})
        with self.assertRaises(AccountSettingRejected):
            client.reaffirm_isolated("501")

    def test_normal_fire_guard_still_refuses_missing_margin_proof(self):
        with patch(
            "tradebot.fire_account_guard.signed_account_margin_mode",
            side_effect=ValueError("missing_signed_mode"),
        ):
            with self.assertRaises(ValueError):
                require_flat_demo_account(self.client)
        self.assertEqual(self.client.calls, [])

    def test_existing_order_capable_fire_client_still_uses_full_exposure_guard(self):
        # Standard FIRE performs its signed isolated-margin proof first,
        # then runs the same account-wide scans with an order-capable client.
        broker = FlatDemoBroker()
        broker.allow_orders = True
        with patch(
            "tradebot.fire_account_guard.signed_account_margin_mode",
            return_value="isolated",
        ):
            checked = require_flat_demo_account(broker)
        self.assertTrue(checked["account_flat_verified"])
        self.assertEqual(checked["checked_markets"], ["BTCUSD", "XAUTUSD"])
        with self.assertRaises(AccountExposureRejected):
            require_flat_demo_account_for_configuration(broker)

    def test_configuration_flatness_is_not_margin_verification(self):
        flat=require_flat_demo_account_for_configuration(self.client)
        self.assertTrue(flat["account_flat_verified"])
        self.assertEqual(flat["checked_markets"], ["BTCUSD","XAUTUSD"])
        self.assertTrue(all(method == "GET" for method,_,_ in self.client.calls))


if __name__=="__main__":
    unittest.main()
