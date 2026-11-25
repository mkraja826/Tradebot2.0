import json
import unittest
from urllib.error import HTTPError
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
