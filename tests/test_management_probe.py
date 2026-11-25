"""Actual provider request/parser exercised with synthetic transport only."""
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch
from recover_trading.decision import Provider
from recover_trading import management_probe as mp

class FakeResponse(io.BytesIO):
    pass

class ManagementProbeTests(unittest.TestCase):
    def transport(self, content, finish="stop"):
        payload={"choices":[{"finish_reason":finish,"message":{
            "reasoning_content":"not part of the final answer","content":content}}],
            "usage":{"prompt_tokens":100,"completion_tokens":40,"total_tokens":140}}
        opener=Mock()
        opener.open.return_value=FakeResponse(json.dumps(payload).encode())
        return opener

    def test_valid_response_and_model_routing(self):
        for symbol in ("BTCUSD","XAUTUSD"):
            for direction in ("LONG","SHORT"):
                with self.subTest(symbol=symbol,direction=direction):
                    fixture=mp.context(symbol,"profit_retention",direction)
                    content=json.dumps({"symbol":symbol,"action":"reduce","contracts":3,"reason":"synthetic"})
                    opener=self.transport(content)
                    result=mp.probe(Provider(api_key="fixture",opener=opener),mp.DEFAULT_MANAGEMENT_MODEL,fixture)
                    self.assertEqual(result["status"],"valid_proposal")
                    self.assertEqual(abs(result["expected_size"]),7)
                    self.assertEqual(result["provider_diagnostics"]["usage"]["total_tokens"],140)
                    self.assertGreaterEqual(result["elapsed_ms"],0)
                    self.assertEqual(result["execution_effect"],"none")
                    opener.open.assert_called_once()
                    request=opener.open.call_args.args[0]
                    self.assertEqual(json.loads(request.data)["model"],mp.DEFAULT_MANAGEMENT_MODEL)
                    self.assertEqual(json.loads(json.loads(request.data)["messages"][1]["content"])["symbol"],symbol)

    def test_invalid_truncated_and_reasoning_only_responses(self):
        fixture=mp.context("BTCUSD","loss_reduction","LONG")
        good=json.dumps({"symbol":"BTCUSD","action":"close","reason":"fixture"})
        for content,finish in ((good,"length"),("", "stop"),("not json","stop"),
            (json.dumps({"symbol":"XAUTUSD","action":"close","reason":"fixture"}),"stop")):
            with self.subTest(content=content,finish=finish):
                opener=self.transport(content,finish)
                r=mp.probe(Provider(api_key="fixture",opener=opener),mp.DEFAULT_MANAGEMENT_MODEL,fixture)
                self.assertEqual(r["status"],"failed")
                self.assertEqual(r["execution_effect"],"none")
                opener.open.assert_called_once()

    def test_timeout_no_retry(self):
        opener=Mock()
        opener.open.side_effect=TimeoutError
        r=mp.probe(Provider(api_key="fixture",opener=opener),mp.DEFAULT_MANAGEMENT_MODEL,
                   mp.context("XAUTUSD","winner_extension","SHORT"))
        self.assertEqual(r["status"],"failed")
        self.assertEqual(r["error"],"TimeoutError")
        opener.open.assert_called_once()

    def test_default_cli_no_provider_call(self):
        out=io.StringIO()
        with patch.object(sys,"argv",["probe"]),patch.object(mp,"Provider") as provider,redirect_stdout(out):
            self.assertEqual(mp.main(),0)
            provider.assert_not_called()
        self.assertEqual(json.loads(out.getvalue())["provider_calls"],0)
