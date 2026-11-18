import json
import unittest
from unittest.mock import Mock

from tradebot.ai import AIPlanner, PlanError, PRIMARY_MODEL
from tradebot.fire_probe import ROLES, run_probe, validate

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
                calls.append(body["model"])
                answer = json.dumps(PLAN)
                return {"choices": [{"message": {"content": answer}}]}
        snapshot = Mock(return_value={"core": CORE, "collected_at": "example"})
        report = run_probe(ROLES, snapshot, Client)
        snapshot.assert_called_once()
        self.assertEqual(ROLES, {"fire": "tb-gpt-6"})
        self.assertEqual(calls, ["tb-gpt-6"])
        self.assertEqual(list(report["results"]), ["fire"])
        self.assertEqual(report["results"]["fire"]["decision"]["contracts"], 2)

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

    def test_observer_still_uses_primary_route(self):
        self.assertEqual(AIPlanner(model=PRIMARY_MODEL).model, PRIMARY_MODEL)
        with self.assertRaises(PlanError):
            AIPlanner(model=ROLES["fire"])
