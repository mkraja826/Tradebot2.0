import json
import unittest
from unittest.mock import Mock

from tradebot.ai import AIPlanner, PlanError, PRIMARY_MODEL
from tradebot.fire_probe import ROLES, run_probe, validate

CORE = {"best_bid": "100", "best_ask": "101"}
PLAN = dict(direction="LONG", contracts=2, stop_loss=95, take_profit=109)


class FireProbeTest(unittest.TestCase):
    def test_shared_snapshot_and_partial_failure(self):
        calls = {}
        class Client:
            last_request_id = "example"
            def _call(self, url, *, body=None, timeout):
                if body is None:
                    return {"data": [{"id": m} for m in ROLES.values()]}
                calls[body["model"]] = body["messages"][-1]["content"]
                answer = json.dumps(PLAN) if body["model"] == ROLES["fire"] else "bad"
                return {"choices": [{"message": {"content": answer}}]}
        snapshot = Mock(return_value={"core": CORE, "collected_at": "example"})
        report = run_probe(ROLES, snapshot, Client)
        snapshot.assert_called_once()
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(set(calls.values())), 1)
        self.assertEqual(report["results"]["fire"]["decision"]["contracts"], 2)
        self.assertIn("error", report["results"]["paper"])

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
