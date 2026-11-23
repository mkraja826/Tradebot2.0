import json
import unittest
from unittest.mock import Mock, patch

from tradebot.ai import AIPlanner, PlanError, PRIMARY_MODEL
from tradebot.fire_probe import ROLES, decision_failure_code, decision_payload, run_probe, validate

CORE = {"best_bid": "100", "best_ask": "101"}
PLAN = dict(direction="LONG", contracts=2, stop_loss=95, take_profit=109)


class FireProbeTest(unittest.TestCase):
    def test_single_gpt6_completion_no_kimi(self):
        calls = []
        class Client:
            last_request_id = "example"
            def _call(self, url, *, body=None, timeout):
                if body is None:
                    return {"data": [{"id": ROLES["fire"]}]}
                calls.append(body)
                answer = json.dumps(PLAN)
                return {"choices": [{"message": {"content": answer}}]}
        snapshot = Mock(return_value={"core": CORE, "collected_at": "example"})
        report = run_probe(ROLES, snapshot, Client)
        snapshot.assert_called_once()
        self.assertEqual(ROLES, {"fire": "tb-gpt-6"})
        self.assertEqual([row["model"] for row in calls], ["tb-gpt-6"])
        self.assertEqual(calls[0]["max_completion_tokens"], 1024)
        self.assertNotIn("response_format", calls[0])
        self.assertEqual(list(report["results"]), ["fire"])
        self.assertEqual(report["results"]["fire"]["decision"]["contracts"], 2)

    def test_wait_is_valid_only_with_zero_contracts_and_no_exit_orders(self):
        no_trade = {"direction":"WAIT","contracts":0,
                    "stop_loss":None,"take_profit":None,
                    "thesis":"No verified entry with adequate net reward-to-risk."}
        self.assertEqual(validate(no_trade,CORE)["direction"],"WAIT")
        normalized = validate(no_trade, CORE, require_leverage=True)
        self.assertEqual(normalized["thesis"], no_trade["thesis"])
        self.assertIsNone(normalized["leverage"])
        self.assertEqual(
            validate(normalized, CORE, require_leverage=True), normalized)
        with self.assertRaises(PlanError):
            validate(no_trade | {"contracts":1},CORE)
        with self.assertRaises(PlanError):
            validate(no_trade | {"thesis":""},CORE)
        with self.assertRaises(PlanError):
            validate(no_trade | {"take_profit":"111"},CORE)

    def test_gpt6_wait_roundtrips_through_execution_validator(self):
        calls = []
        wait = {
            "direction": "WAIT", "contracts": 0, "leverage": None,
            "stop_loss": None, "take_profit": None,
            "thesis": "Insufficient verified price evidence for a safe entry.",
        }
        class Client:
            last_request_id = None
            def _call(self, url, *, body=None, timeout):
                if body is None:
                    return {"data": [{"id": ROLES["fire"]}]}
                calls.append("one_model_request")
                return {"choices": [
                    {"message": {"content": json.dumps(wait)}, "finish_reason": "stop"}]}
        snapshot = lambda: {
            "core": CORE, "collected_at": "example",
            "fire_execution_scope": {"dynamic_leverage_enabled": True},
        }
        report = run_probe(ROLES, snapshot, Client)
        self.assertEqual(calls, ["one_model_request"])
        intermediate = report["results"]["fire"]["decision"]
        second = validate(intermediate, CORE, require_leverage=True)
        self.assertEqual(second["direction"], "WAIT")
        self.assertEqual(second["contracts"], 0)
        self.assertEqual(second["thesis"], wait["thesis"])

    def test_autonomous_prompt_requires_net_cost_aware_ratio(self):
        from tradebot.fire_probe import (
            AUTONOMOUS_BTC_DIRECTION_INSTRUCTION, INSTRUCTION)
        prompt = AUTONOMOUS_BTC_DIRECTION_INSTRUCTION
        self.assertIn("at least 1.5", prompt)
        self.assertIn("taker_commission_rate", prompt)
        self.assertIn("0.0005", prompt)
        self.assertIn("contract_value", prompt)
        self.assertIn("never fabricate a distant", prompt)
        # This DEMO-only prompt change must not alter standard FIRE.
        self.assertNotIn("at least 1.5", INSTRUCTION)

    def test_autonomous_direction_policy_rejects_wait_without_retry(self):
        from tradebot.fire_probe import AUTONOMOUS_BTC_DIRECTION_INSTRUCTION
        self.assertIn("Direction must be LONG or SHORT", AUTONOMOUS_BTC_DIRECTION_INSTRUCTION)
        observed = []
        response = {
            "direction": "WAIT", "contracts": 0, "leverage": None,
            "stop_loss": None, "take_profit": None,
            "thesis": "No appropriate entry",
        }

        class Client:
            last_request_id = None
            def _call(self, url, *, body=None, timeout):
                if body is None:
                    return {"data": [{"id": ROLES["fire"]}]}
                observed.append(body)
                return {"choices": [{"message": {"content": json.dumps(response)},
                                     "finish_reason": "stop"}]}

        # Mock only the instruction's original-local-history prerequisite;
        # production still validates the true signed historical context.
        snap = {
            "core": CORE, "collected_at": "example",
            "fire_execution_scope": {
                "unattended_demo_mode": True,
                "dynamic_leverage_enabled": True,
            },
        }
        with patch("tradebot.fire_probe.instruction_for_snapshot",
                   return_value=AUTONOMOUS_BTC_DIRECTION_INSTRUCTION):
            report = run_probe(ROLES, lambda: snap, Client)
        self.assertEqual(len(observed), 1)
        result = report["results"]["fire"]
        self.assertNotIn("decision", result)
        self.assertEqual(result["error_stage"], "validation")
        self.assertEqual(decision_failure_code(
            result["error"], stage=result["error_stage"]),
            "autonomous_invalid_wait")
        self.assertNotIn("No appropriate entry", str(result))

    def test_autonomous_direction_policy_accepts_valid_long_and_short(self):
        observed = []
        class Client:
            last_request_id = None
            def _call(self, url, *, body=None, timeout):
                if body is None:
                    return {"data": [{"id": ROLES["fire"]}]}
                observed.append(body)
                return {"choices": [{"message": {"content": json.dumps(body_plan)},
                                     "finish_reason": "stop"}]}

        snap = {
            "core": CORE, "collected_at": "example",
            "fire_execution_scope": {
                "unattended_demo_mode": True,
                "dynamic_leverage_enabled": True,
            },
        }
        for body_plan in (
            {"direction": "LONG", "contracts": 1, "leverage": 3,
             "stop_loss": 95, "take_profit": 109,
             "thesis": "Test directional candidate"},
            {"direction": "SHORT", "contracts": 1, "leverage": 3,
             "stop_loss": 109, "take_profit": 95,
             "thesis": "Test directional candidate"},
        ):
            with self.subTest(direction=body_plan["direction"]), patch(
                    "tradebot.fire_probe.instruction_for_snapshot",
                    return_value="long or short only"):
                response = run_probe(ROLES, lambda: snap, Client)
            self.assertEqual(
                response["results"]["fire"]["decision"]["direction"],
                body_plan["direction"])
        self.assertEqual(len(observed), 2)

    def test_single_fenced_object_still_requires_valid_finished_decision(self):
        choice = {"message": {"content": "```json\n" + json.dumps(PLAN) + "\n```"}, "finish_reason":"stop"}
        self.assertEqual(validate(decision_payload(choice), CORE)["contracts"], 2)
        with self.assertRaises(PlanError):
            decision_payload(dict(choice, finish_reason="length"))
        with self.assertRaises(ValueError):
            decision_payload({"message":{"content":"extra prose " + choice["message"]["content"]}})

    def test_public_error_codes_exclude_arbitrary_provider_text(self):
        self.assertEqual(decision_failure_code("Top Billing API HTTP 402"), "provider_http_402")
        self.assertEqual(decision_failure_code("sensitive upstream body"), "model_decision_failed")

    def test_unknown_provider_failure_gets_bounded_reason_code(self):
        class Client:
            last_request_id = None
            def _call(self, url, *, body=None, timeout):
                if body is None:
                    return {"data": [{"id": ROLES["fire"]}]}
                raise PlanError("upstream-opaque-message-that-must-not-persist")
        report = run_probe(ROLES, lambda: {
            "core": CORE, "collected_at": "example"}, Client)
        result = report["results"]["fire"]
        self.assertEqual(result["error_stage"], "provider_request")
        self.assertEqual(decision_failure_code(
            result["error"], stage=result["error_stage"]),
            "provider_unclassified_failure")
        self.assertEqual(decision_failure_code(
            "upstream-opaque-message-that-must-not-persist"), "model_decision_failed")

    def test_unknown_validation_failure_gets_bounded_reason_code(self):
        class Client:
            last_request_id = None
            def _call(self, url, *, body=None, timeout):
                if body is None:
                    return {"data": [{"id": ROLES["fire"]}]}
                return {"choices": [{"message": {"content": json.dumps(PLAN)}}]}
        with patch("tradebot.fire_probe.validate",
                   side_effect=PlanError("nonspecific private model failure")):
            result = run_probe(ROLES, lambda: {
                "core": CORE, "collected_at": "example"}, Client)["results"]["fire"]
        self.assertEqual(result["error_stage"], "validation")
        self.assertEqual(decision_failure_code(
            result["error"], stage=result["error_stage"]),
            "model_unclassified_validation_failure")

    def test_missing_model_choice_is_classified_without_retry(self):
        calls = []
        class Client:
            last_request_id = None
            def _call(self, url, *, body=None, timeout):
                if body is None:
                    return {"data": [{"id": ROLES["fire"]}]}
                calls.append("completion")
                return {"choices": []}
        result = run_probe(ROLES, lambda: {
            "core": CORE, "collected_at": "example"}, Client)["results"]["fire"]
        self.assertEqual(calls, ["completion"])
        self.assertEqual(result["error_stage"], "completion")
        self.assertEqual(decision_failure_code(
            result["error"], stage=result["error_stage"]), "model_invalid_json")

    def test_kimi_or_second_route_is_refused_before_any_model_call(self):
        client = Mock()
        snapshot = Mock()
        for routes in ({"fire": "tb-kimi-k3-1-pro"},
                       {"fire": "tb-gpt-6", "paper": "tb-kimi-k3-1-pro"}):
            with self.subTest(routes=routes), self.assertRaises(PlanError):
                run_probe(routes, snapshot, lambda: client)
        client._call.assert_not_called()
        snapshot.assert_not_called()

    def test_missing_route_stops_before_paid_calls(self):
        client = Mock()
        client._call.return_value = {"data": []}
        snapshot = Mock()
        with self.assertRaises(PlanError):
            run_probe(ROLES, snapshot, lambda: client)
        snapshot.assert_not_called()
        client._call.assert_called_once()

    def test_invalid_decisions(self):
        for change in (dict(direction="WAIT"), dict(contracts=True), dict(contracts=0),
                       dict(stop_loss="NaN"), dict(take_profit=99), dict(direction="SHORT")):
            with self.subTest(change=change), self.assertRaises(PlanError):
                validate(PLAN | change, CORE)
        self.assertEqual(validate(PLAN | dict(direction="SHORT", stop_loss=109, take_profit=95),
                                  CORE)["direction"], "SHORT")

    def test_dynamic_leverage_schema_fails_closed(self):
        for leverage in (0, 21, True, 2.5, "5", None):
            with self.subTest(leverage=leverage), self.assertRaises(PlanError):
                validate(PLAN | {"leverage": leverage}, CORE, require_leverage=True)
        self.assertEqual(validate(PLAN | {"leverage":20}, CORE,
                                  require_leverage=True)["leverage"], 20)
        with self.assertRaises(PlanError):
            validate(PLAN, CORE, require_leverage=True)

    def test_observer_still_uses_primary_route(self):
        self.assertEqual(AIPlanner(model=PRIMARY_MODEL).model, PRIMARY_MODEL)
        with self.assertRaises(PlanError):
            AIPlanner(model=ROLES["fire"])
