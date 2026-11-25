import json
import unittest
from urllib.error import HTTPError, URLError
from recover_trading.decision import parse_completion, Provider, ProviderResponseError

def envelope(content, finish="stop"):
    return {"choices":[{"finish_reason":finish,"message":{"content":content}}]}

class ProviderTests(unittest.TestCase):
    def test_plain_and_fenced_json(self):
        for text in ('{"action":"no_trade"}', '```JSON\n{"action":"no_trade"}\n```', '```\n{"action":"no_trade"}\n```'):
            self.assertEqual(parse_completion(envelope(text)),{"action":"no_trade"})
    def test_bad_and_incomplete_responses(self):
        for data, code in [(envelope('{"action":"trade"}',"length"),"completion_limit"),
                           (envelope(""),"empty_content"),(envelope("reasoning only"),"invalid_json"),
                           (envelope("[]"),"not_object"),({},"invalid_envelope")]:
            with self.subTest(code=code):
                with self.assertRaises(ProviderResponseError) as cm:
                    parse_completion(data)
                self.assertEqual(cm.exception.code,code)
    def test_request_budget_and_diagnostics(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self,n): return json.dumps(envelope('{"action":"no_trade"}')).encode()
        class Opener:
            def open(self,req,timeout):
                self.timeout=timeout
                self.body=json.loads(req.data)
                return Response()
        opener=Opener()
        p=Provider(api_key="fake",opener=opener)
        self.assertEqual(p.propose("fake",{}),{"action":"no_trade"})
        self.assertEqual(opener.timeout,90)
        self.assertEqual(opener.body["max_completion_tokens"],8192)
        self.assertEqual(p.diagnostics["finish_reason"],"stop")
        self.assertNotIn("fake",str(p.diagnostics))

    def test_http_error_status_is_recorded_without_sensitive_body(self):
        class Opener:
            def open(self,req,timeout):
                raise HTTPError("https://example.invalid",429,"private error text",{},None)
        p=Provider(api_key="fake",opener=Opener())
        with self.assertRaises(ProviderResponseError) as cm:
            p.propose("fake",{})
        self.assertEqual(cm.exception.code,"http_429")
        self.assertEqual(p.diagnostics["http_status"],429)
        self.assertNotIn("private error text",str(p.diagnostics))

    def test_strict_completion_rejects_ambiguous_json(self):
        for raw in ('{"action":"trade","action":"no_trade"}','{"price":NaN}','{"price":Infinity}'):
            with self.assertRaises(ProviderResponseError) as cm:
                parse_completion(envelope(raw))
            self.assertEqual(cm.exception.code,"invalid_json")

    def test_wrapped_timeout_phase(self):
        class Opener:
            def open(self,*args,**kwargs):
                raise URLError(TimeoutError("private"))
        p=Provider(api_key="fixture",opener=Opener())
        with self.assertRaises(TimeoutError):p.propose("fake",{})
        self.assertEqual(p.diagnostics["phase"],"connect_or_headers")
        self.assertEqual(p.diagnostics["transport_failure"],"timeout")
        self.assertNotIn("private",str(p.diagnostics))

    def test_body_timeout_distinguished(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,n):raise TimeoutError()
        class Opener:
            def open(self,*args,**kwargs):return Response()
        p=Provider(api_key="fixture",opener=Opener())
        with self.assertRaises(TimeoutError):p.propose("fake",{})
        self.assertEqual(p.diagnostics["phase"],"response_body")
        self.assertIn("headers_ms",p.diagnostics)

    def test_successful_diagnostics_archived_not_proposal(self):
        import tempfile,sqlite3
        from pathlib import Path
        from recover_trading.decision import DecisionJournal,evaluate_report
        from test_recover_decision import report
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,n):return json.dumps(envelope('{"symbol":"BTCUSD","action":"no_trade","reason":"fixture"}')).encode()
        class Opener:
            def open(self,*args,**kwargs):return Response()
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"decisions"; j=DecisionJournal(p)
            result=evaluate_report(report(),j,Provider(api_key="fixture",opener=Opener()),{"BTCUSD":"fake"})
            self.assertEqual(result["status"],"proposed")
            self.assertNotIn("diagnostics",result["proposal"])
            with sqlite3.connect(p) as db:
                raw=json.loads(db.execute("SELECT result FROM decisions").fetchone()[0])
            self.assertEqual(raw["diagnostics"]["phase"],"proposal_validated")
            self.assertGreater(raw["diagnostics"]["response_bytes"],0)
