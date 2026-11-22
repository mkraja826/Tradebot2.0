"""Offline tests for the single-command read-only BTC DEMO evidence packet."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tradebot.delta import DEMO_API
from tradebot.demo_release_evidence import (
    _clock_synchronized, observe_demo_release,
)

FIRE_ID = "a" * 32


class DemoReadOnly:
    base_url = DEMO_API
    allow_orders = False


def healthy(_path):
    return {
        "status": "healthy", "checkpoint_prerequisites_met": True,
        "trade_authorized": False, "blocking_conditions": [],
        "monitoring": {
            "watchdog": "healthy", "watchdog_age_seconds": 3.0,
            "equity_collector": "healthy",
            "equity_collector_age_seconds": 8.0,
            "alert_codes": [],
        },
    }


def within_budget(_exchange, _root):
    return {
        "approved": True,
        "reason": "within_observed_equity_limits",
        "source": "delta_demo_signed_wallet",
        "mode": "read_only", "evidence_persisted": False,
        "is_reconciled_realized_pnl": False, "trade_authorized": False,
        "health": healthy(None), "read_receipt": {
            "SECRET_RESPONSE": "SECRET_BALANCE_ACCOUNT_NEVER_PUBLISH",
        },
        "equity_usd": "SECRET_ACCOUNT_BALANCE_NEVER_PUBLISH",
    }


def flat_inventory(*_args, **_kwargs):
    return {
        "observation_status": "two_flat_snapshots_observed_not_trade_authority",
        "samples_checked": 2, "sample_interval_verified": True,
        "broker_positions_last": 0, "broker_open_orders_last": 0,
        "order_mutations": False, "trade_authorized": False, "blockers": [],
    }


def historical_match(*_args, **_kwargs):
    return {
        "observation_status": "historical_order_fields_match_not_protection_proof",
        "authenticated_order_gets": 3,
        "local_evidence_stable_across_order_reads": True,
        "trade_authorized": False, "safe_to_enable_fire": False,
        "is_historical_protection_proven": False,
        "order_mutations": False, "blockers": [],
    }


class DemoEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.broker = DemoReadOnly()
        self.inventory_calls = []
        self.bracket_calls = []

    def observe(self, **overrides):
        def inventory(*args, **kwargs):
            self.inventory_calls.append((args, kwargs))
            return flat_inventory()
        def bracket(*args, **kwargs):
            self.bracket_calls.append((args, kwargs))
            return historical_match()
        options = {
            "fire_id": FIRE_ID, "clock_check": lambda: True,
            "service_check": lambda: True,
            "fire_disabled_check": lambda: True,
            "health_check": healthy, "budget_check": within_budget,
            "inventory_check": inventory,
            "bracket_check": bracket,
            "pause": lambda _: None,
        }
        options.update(overrides)
        return observe_demo_release(self.broker, self.root, **options)

    def test_consistent_broker_observations_never_grant_trade_authority(self):
        report = self.observe()
        self.assertEqual(
            report["status"], "limited_read_only_checks_consistent_not_execution_authority")
        self.assertEqual(report["blockers"], [])
        self.assertEqual(len(self.inventory_calls), 1)
        self.assertEqual(len(self.bracket_calls), 1)
        self.assertEqual(self.bracket_calls[0][1],
                         {"symbol": "BTCUSD", "fire_id": FIRE_ID})
        self.assertTrue(all(report["checks"].values()))
        self.assertFalse(report["trade_authorized"])
        self.assertFalse(report["safe_to_enable_fire"])
        self.assertFalse(report["ready_for_unattended_trading"])
        self.assertFalse(report["broker_order_mutations"])
        self.assertFalse(report["local_ledger_mutations"])
        self.assertTrue(report["fresh_wallet_risk_assessment_completed"])
        self.assertTrue(report["checks"]["monitor_heartbeats_verified"])
        self.assertTrue(report["checks"]["fresh_wallet_loss_budget_within_limits"])
        self.assertNotIn("SECRET_", json.dumps(report))
        self.assertFalse(report["broker_wide_fill_and_funding_reconciliation_complete"])
        self.assertFalse(report["historical_continuous_protection_proven"])
        self.assertTrue(report["independent_risk_review_required"])
        self.assertEqual(report["ai_calls"], 0)
        self.assertNotIn(FIRE_ID, json.dumps(report))

    def test_invalid_fire_id_fails_before_health_or_broker_reads(self):
        for bad in ("not-hex", "b" * 31, "B" * 32, None, [], 77):
            with self.subTest(bad=bad):
                report = self.observe(fire_id=bad,
                                      clock_check=lambda: self.fail("clock read"))
                self.assertIn("invalid_completed_btc_fire_id", report["blockers"])
                self.assertEqual(self.inventory_calls, [])
                self.assertEqual(self.bracket_calls, [])

    def test_mutation_capable_or_non_demo_client_rejected_first(self):
        for attr, bad in (("allow_orders", True), ("allow_orders", 0),
                          ("base_url", "https://live.exchange")):
            with self.subTest(attr=attr, bad=bad):
                setattr(self.broker, attr, bad)
                report = self.observe()
                self.assertEqual(report["blockers"],
                                 ["read_only_delta_demo_client_required"])
                self.assertEqual(self.inventory_calls, [])
                self.assertEqual(self.bracket_calls, [])
                setattr(self.broker, attr, False if attr == "allow_orders" else DEMO_API)

    def test_untrusted_missing_or_symlinked_source_blocks_without_writes(self):
        missing = self.root / "missing"
        result = observe_demo_release(self.broker, missing, fire_id=FIRE_ID)
        self.assertEqual(result["blockers"], ["trusted_original_data_directory_required"])
        self.assertFalse(missing.exists())
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        report = observe_demo_release(self.broker, alias, fire_id=FIRE_ID)
        self.assertEqual(report["blockers"], ["trusted_original_data_directory_required"])

    def test_failed_clock_or_watchdog_or_disabled_dashboard_skips_broker(self):
        report = self.observe(clock_check=lambda: False,
                              service_check=lambda: False,
                              fire_disabled_check=lambda: False)
        self.assertEqual(set(report["blockers"]), {
            "system_clock_not_verified",
            "required_monitor_services_unverified",
            "dashboard_fire_disabled_unverified",
        })
        self.assertEqual(self.inventory_calls, [])
        self.assertEqual(self.bracket_calls, [])

    def test_missing_or_stale_equity_checkpoint_is_blocker(self):
        status = {"status": "checkpoint_missed", "checkpoint_prerequisites_met": False,
                  "trade_authorized": False, "blocking_conditions": ["daily_missed"]}
        report = self.observe(health_check=lambda _p: status)
        self.assertIn("signed_equity_checkpoint_health_unverified",
                      report["blockers"])
        self.assertEqual(self.inventory_calls, [])
        self.assertEqual(self.bracket_calls, [])

    def test_equity_health_must_explicitly_deny_trade_permission(self):
        health = lambda _p: {**healthy(None), "trade_authorized": True}
        report = self.observe(health_check=health)
        self.assertIn("signed_equity_checkpoint_health_unverified", report["blockers"])

    def test_missing_or_stale_watchdog_heartbeat_blocks_before_wallet_or_broker(self):
        for status, age, codes in (
            ("stale", 91.0, ["watchdog_heartbeat_stale"]),
            ("healthy", 91.0, []),
            ("healthy", -1.0, []),
            ("healthy", "0", []),
            ("healthy", None, []),
        ):
            with self.subTest(status=status,age=age):
                health = healthy(None)
                health["monitoring"]["watchdog"] = status
                health["monitoring"]["watchdog_age_seconds"] = age
                health["monitoring"]["alert_codes"] = codes
                budget_calls = []
                def budget(*args):
                    budget_calls.append(args)
                    return within_budget(*args)
                report = self.observe(
                    health_check=lambda _p: health, budget_check=budget)
                self.assertIn(
                    "watchdog_or_equity_collector_heartbeat_unverified",
                    report["blockers"])
                self.assertFalse(report["checks"]["monitor_heartbeats_verified"])
                self.assertFalse(report["fresh_wallet_risk_assessment_completed"])
                self.assertEqual(budget_calls, [])
                self.assertEqual(self.inventory_calls, [])
                self.assertEqual(self.bracket_calls, [])

    def test_no_monitoring_row_is_not_interpreted_as_a_healthy_service(self):
        result = self.observe(health_check=lambda _p: {
            "status": "healthy",
            "checkpoint_prerequisites_met": True,
            "trade_authorized": False,
            "blocking_conditions": [],
        })
        self.assertFalse(result["checks"]["monitor_heartbeats_verified"])
        self.assertIn(
            "watchdog_or_equity_collector_heartbeat_unverified",
            result["blockers"])
        self.assertEqual(self.inventory_calls, [])

    def test_stale_collector_heartbeat_stops_before_signed_wallet_read(self):
        health = healthy(None)
        health["monitoring"]["equity_collector_age_seconds"] = 181.
        budget_calls = []
        report = self.observe(
            health_check=lambda _p: health,
            budget_check=lambda *args: budget_calls.append(args))
        self.assertIn(
            "watchdog_or_equity_collector_heartbeat_unverified",
            report["blockers"])
        self.assertEqual(budget_calls, [])
        self.assertEqual(self.inventory_calls, [])

    def test_fresh_wallet_budget_loss_limit_stops_broker_inventory(self):
        failed = {**within_budget(None,None), "approved": False,
                  "reason": "loss_limit_daily", "equity_usd": "PRIVATE_980"}
        report = self.observe(budget_check=lambda *_args: failed)
        self.assertIn("fresh_signed_wallet_loss_budget_unverified",
                      report["blockers"])
        self.assertFalse(report["checks"]["fresh_wallet_loss_budget_within_limits"])
        self.assertFalse(report["fresh_wallet_risk_assessment_completed"])
        self.assertFalse(report["trade_authorized"])
        self.assertNotIn("PRIVATE_980", json.dumps(report))
        self.assertEqual(self.inventory_calls, [])
        self.assertEqual(self.bracket_calls, [])

    def test_wallet_budget_provenance_and_no_ledger_write_are_required(self):
        for key, value in (
            ("trade_authorized", True), ("mode","order_enabled"),
            ("evidence_persisted",True), ("is_reconciled_realized_pnl",True),
            ("source","unknown"), ("approved", False),
            ("health", {**healthy(None), "status": "monitoring_degraded"}),
        ):
            with self.subTest(key=key):
                report = self.observe(
                    budget_check=lambda *_args: {
                        **within_budget(None,None), key:value})
                self.assertIn(
                    "fresh_signed_wallet_loss_budget_unverified",
                    report["blockers"])
                self.assertEqual(self.inventory_calls, [])
                self.assertFalse(report["trade_authorized"])

    def test_wallet_failure_is_sanitized_and_no_broker_inventory(self):
        def broken(*args, **kwargs):
            raise RuntimeError("SECRET_ACCOUNT_NUMBER_123")
        report = self.observe(budget_check=broken)
        self.assertIn(
            "fresh_signed_wallet_loss_budget_unverified",
            report["blockers"])
        self.assertNotIn("SECRET_ACCOUNT_NUMBER_123", json.dumps(report))
        self.assertEqual(self.inventory_calls, [])
        self.assertFalse(report["trade_authorized"])

    def test_monitor_heartbeat_change_during_broker_sweep_blocks_report(self):
        reports = iter((healthy(None), {
            **healthy(None),
            "monitoring": {
                **healthy(None)["monitoring"],
                "watchdog_age_seconds": 100.0,
            }
        }))
        report = self.observe(health_check=lambda _p: next(reports))
        self.assertTrue(report["checks"]["fresh_wallet_loss_budget_within_limits"])
        self.assertFalse(report["checks"]["final_host_and_equity_still_healthy"])
        self.assertIn(
            "host_or_equity_changed_during_broker_observation",
            report["blockers"])
        self.assertFalse(report["trade_authorized"])

    def test_broken_clock_or_service_exception_never_exposes_secrets(self):
        def boom():
            raise RuntimeError("PRIVATE_AUTH_TOKEN")
        report = self.observe(clock_check=boom, service_check=boom)
        self.assertIn("system_clock_not_verified", report["blockers"])
        self.assertIn("required_monitor_services_unverified", report["blockers"])
        self.assertNotIn("PRIVATE_AUTH_TOKEN", json.dumps(report))

    def test_incomplete_inventory_skips_historical_broker_get(self):
        def partial(*args, **kwargs):
            return {**flat_inventory(), "samples_checked": 1}
        report = self.observe(inventory_check=partial)
        self.assertEqual(report["status"], "review_required")
        self.assertIn("account_wide_delta_demo_evidence_unverified",
                      report["blockers"])
        self.assertEqual(self.bracket_calls, [])
        self.assertFalse(report["trade_authorized"])

    def test_inventory_exception_sanitized_and_historical_lookup_skipped(self):
        def denied(*args, **kwargs):
            raise ValueError("SECRET TOKEN IN PROVIDER RESPONSE")
        report = self.observe(inventory_check=denied)
        self.assertIn("account_wide_delta_demo_evidence_unverified",
                      report["blockers"])
        self.assertNotIn("SECRET TOKEN", json.dumps(report))
        self.assertEqual(self.bracket_calls, [])

    def test_broker_bracket_field_mismatch_blocks_clean_result(self):
        def inconsistent(*args, **kwargs):
            return {**historical_match(),
                    "local_evidence_stable_across_order_reads": False}
        report = self.observe(bracket_check=inconsistent)
        self.assertIn("historical_btc_bracket_fields_unverified",
                      report["blockers"])
        self.assertEqual(report["status"], "review_required")
        self.assertFalse(report["historical_continuous_protection_proven"])

    def test_historical_exception_is_sanitized(self):
        def boom(*args, **kwargs):
            raise OSError("SECRET API KEY")
        report = self.observe(bracket_check=boom)
        self.assertIn("historical_btc_bracket_fields_unverified",
                      report["blockers"])
        self.assertNotIn("SECRET", json.dumps(report))

    def test_late_clock_service_or_fire_change_blocks_even_after_clean_broker_reads(self):
        for check_name in ("clock_check", "service_check", "fire_disabled_check"):
            with self.subTest(check=check_name):
                observations = iter((True, False))
                report = self.observe(**{check_name: lambda: next(observations)})
                self.assertIn("host_or_equity_changed_during_broker_observation",
                              report["blockers"])
                self.assertEqual(report["status"], "review_required")
                self.assertFalse(report["checks"]["final_host_and_equity_still_healthy"])
                self.assertTrue(report["checks"]["two_flat_broker_samples_observed"])
                self.assertTrue(report["checks"]["historical_order_fields_match"])
                self.assertFalse(report["trade_authorized"])

    def test_late_equity_checkpoint_staleness_blocks_limited_consistency(self):
        reads = iter((healthy(None),
                      {"status": "evidence_stale",
                       "checkpoint_prerequisites_met": False,
                       "trade_authorized": False,
                       "blocking_conditions": ["signed_equity_observation_stale"]}))
        report = self.observe(health_check=lambda _p: next(reads))
        self.assertTrue(report["checks"]["equity_checkpoint_prerequisites_met"])
        self.assertIn("host_or_equity_changed_during_broker_observation",
                      report["blockers"])
        self.assertFalse(report["checks"]["final_host_and_equity_still_healthy"])
        self.assertEqual(report["status"], "review_required")

    def test_final_host_recheck_exception_is_sanitized(self):
        observations = iter((True, RuntimeError("PRIVATE_HOST_SECRET")))
        def service():
            val = next(observations)
            if isinstance(val, Exception):
                raise val
            return val
        report = self.observe(service_check=service)
        self.assertIn("host_or_equity_changed_during_broker_observation",
                      report["blockers"])
        self.assertNotIn("PRIVATE_HOST_SECRET", json.dumps(report))

    def test_clock_sync_requires_explicit_yes(self):
        def completed(out, ret=0):
            return type("Completed", (), {"returncode": ret, "stdout": out})()
        for stdout, return_code, expect in (("yes\n", 0, True),
                                            ("no\n", 0, False),
                                            ("yes\n", 1, False),
                                            ("", 0, False)):
            with self.subTest(stdout=stdout, return_code=return_code):
                with patch("tradebot.demo_release_evidence.subprocess.run",
                           return_value=completed(stdout, return_code)) as run:
                    self.assertEqual(_clock_synchronized(), expect)
                    self.assertFalse(run.call_args.kwargs["check"])
                    self.assertEqual(run.call_args.args[0][0], "timedatectl")


if __name__ == "__main__":
    unittest.main()
