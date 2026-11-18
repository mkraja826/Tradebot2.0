"""Top Billing integration tests are fully offline and use fake credentials."""
import io
import json
import unittest

from tradebot.ai import (
    AIPlanner, ALLOWED_MODELS, PRIMARY_MODEL, PlanError,
    TOPBILLING_CHAT_URL, TOPBILLING_MODELS_URL
)

PRODUCTS = [
    {"id": 1, "symbol": "BTCUSD",
     "contract_type": "perpetual_futures", "state": "live"},
    {"id": 2, "symbol": "C-BTC-90000-271126",
     "contract_type": "call_options", "state": "live"},
    {"id": 3, "symbol": "ETHUSD",
     "contract_type": "perpetual_futures", "state": "live"},
]


class Reply(io.BytesIO):
    def __init__(self, data):
        super().__init__(json.dumps(data).encode("utf-8"))
        self.headers = {"x-request-id": "tb_req_test"}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class FakeTransport:
    def __init__(self, message=None):
        self.requests = []
        self.message = message or {
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": json.dumps({
                    "strategy": "Research hedge",
                    "rationale": "Illustrative test",
                    "orders": [{"product_id": 1, "side": "buy", "size": 2},
                               {"product_id": 2, "side": "sell", "size": 1}],
                })},
            }],
            "usage": {
                "prompt_tokens": 700, "completion_tokens": 180,
                "total_tokens": 880,
            },
        }

    def __call__(self, request, timeout):
        body = None
        if request.data is not None:
            body = json.loads(request.data)
        self.requests.append({
            "url": request.full_url,
            "method": request.get_method(),
            "body": body,
            "timeout": timeout,
            "authorization_is_present":
                request.get_header("Authorization") == "Bearer tb_test_dummy",
        })
        if request.get_method() == "GET":
            return Reply({"object": "list", "data": [
                {"id": PRIMARY_MODEL}, {"id": "tb-unused-model"}]})
        return Reply(self.message)


class TopBillingTests(unittest.TestCase):
    def setUp(self):
        self.transport = FakeTransport()
        self.planner = AIPlanner(api_key="tb_test_dummy",
                                 transport=self.transport)

    def test_only_one_approved_model(self):
        self.assertEqual(ALLOWED_MODELS, {PRIMARY_MODEL})
        self.assertEqual(self.planner.model, PRIMARY_MODEL)
        with self.assertRaises(PlanError):
            AIPlanner(api_key="tb_test_dummy",
                      model="tb-deepseek-v4-pro",
                      transport=self.transport)

    def test_uses_expected_topbilling_endpoint_without_json_schema(self):
        plan = self.planner.propose(
            {"underlying": "BTC", "session": "trading"}, PRODUCTS)
        self.assertEqual(plan.strategy, "Research hedge")
        self.assertEqual(len(plan.orders), 2)
        request = self.transport.requests[0]
        self.assertEqual(request["url"], TOPBILLING_CHAT_URL)
        self.assertEqual(request["method"], "POST")
        self.assertTrue(request["authorization_is_present"])
        self.assertEqual(request["body"]["model"], PRIMARY_MODEL)
        self.assertNotIn("response_format", request["body"])
        self.assertEqual(request["body"]["max_completion_tokens"], 2048)
        self.assertEqual(self.planner.last_usage["total_tokens"], 880)
        self.assertEqual(self.planner.last_request_id, "tb_req_test")
        # API credentials must never be echoed into prompt messages.
        self.assertNotIn("tb_test_dummy", json.dumps(request["body"]))

    def test_model_check_is_read_only(self):
        self.assertTrue(self.planner.check_model_access())
        req = self.transport.requests[0]
        self.assertEqual(req["method"], "GET")
        self.assertEqual(req["url"], TOPBILLING_MODELS_URL)
        self.assertIsNone(req["body"])

    def test_no_secret_is_rejected_without_network(self):
        empty = AIPlanner(api_key="", transport=self.transport)
        with self.assertRaises(PlanError):
            empty.check_model_access()
        self.assertEqual(self.transport.requests, [])

    def test_markdown_json_is_rejected_and_never_parsed_as_order(self):
        self.transport.message["choices"][0]["message"]["content"] = (
            '```json\n{"strategy":"wait","rationale":"x","orders":[]}\n```')
        with self.assertRaises(PlanError):
            self.planner.propose({}, PRODUCTS)

    def test_non_btc_leg_is_rejected(self):
        self.transport.message["choices"][0]["message"]["content"] = json.dumps({
            "strategy": "bad", "rationale": "no",
            "orders": [{"product_id": 3, "side": "buy", "size": 1}],
        })
        with self.assertRaises(PlanError):
            self.planner.propose({}, PRODUCTS)

    def test_cutoff_response_is_rejected(self):
        self.transport.message["choices"][0]["finish_reason"] = "length"
        with self.assertRaises(PlanError):
            self.planner.propose({}, PRODUCTS)

    def test_empty_model_response_is_rejected(self):
        self.transport.message["choices"][0]["message"]["content"] = ""
        with self.assertRaises(PlanError):
            self.planner.propose({}, PRODUCTS)

    def test_wait_remains_valid(self):
        self.transport.message["choices"][0]["message"]["content"] = json.dumps({
            "strategy": "WAIT", "rationale": "No edge", "orders": [],
        })
        self.assertEqual(self.planner.propose({}, PRODUCTS).orders, ())


if __name__ == "__main__":
    unittest.main()
