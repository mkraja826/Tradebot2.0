import io
import json
import unittest
from unittest.mock import Mock
from approval_verify import request_digest
from operator_auth import approval_challenge
from gold_approval_web import application, HOST, ORIGIN, BASE


class WebTests(unittest.TestCase):
    def setUp(self):
        self.rid = "a"*32
        self.record = {"id": self.rid, "arguments": {"commit_sha": "b"*40}}
        self.api = Mock(policy={"origin": ORIGIN, "rp_id": HOST})
        self.api.request.return_value = self.record
        self.app = application(self.api, [b"enrolled"])

    def call(self, action="", body=None, **overrides):
        raw = json.dumps(body or {}).encode()
        env = {"wsgi.url_scheme": "https", "HTTP_HOST": HOST, "HTTP_ORIGIN": ORIGIN,
               "REQUEST_METHOD": "POST" if action else "GET", "CONTENT_TYPE": "application/json",
               "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw),
               "PATH_INFO": BASE + ("/"+self.rid+"/"+action if action else "")}
        env.update(overrides)
        statuses = []
        result = self.app(env, lambda status, headers: statuses.append(status))
        return statuses[0], b"".join(result)

    def test_page(self):
        self.assertIn(b"Approve release with passkey", self.call()[1])

    def test_wrong_origin(self):
        self.assertEqual(self.call("review", HTTP_ORIGIN="https://example.org")[0], "403 Forbidden")

    def test_review(self):
        self.assertEqual(json.loads(self.call("review")[1])["digest"], request_digest(self.record))

    def test_changed_review(self):
        self.assertEqual(self.call("challenge", {"digest": "wrong"})[0], "409 Conflict")
        self.api.challenge.assert_not_called()

    def test_challenge(self):
        nonce = "d"*64
        self.api.challenge.return_value = {"nonce": nonce, "challenge": approval_challenge(self.record, nonce).hex()}
        result = json.loads(self.call("challenge", {"digest":request_digest(self.record)})[1])
        self.assertEqual(result["rpId"], HOST)
        self.assertEqual(len(result["challenge"]), 43)

    def test_receipt(self):
        self.api.approve.return_value = {"status": "reserved", "signature": "private"}
        _, raw = self.call("approve", {"digest":request_digest(self.record), "nonce":"d"*64, "assertion":"mock"})
        self.assertEqual(json.loads(raw), {"request_id":self.rid, "status":"reserved"})
