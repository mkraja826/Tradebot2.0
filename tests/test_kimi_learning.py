"""Kimi can only learn from read-only facts and cannot teach GPT-6 by default."""
import json
from pathlib import Path
import tempfile
import unittest

from tradebot.kimi_learning import KIMI_REVIEW_MODEL, KimiLearningReviewer
from tradebot.trade_memory import TradeMemory


class KimiReviewTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = TradeMemory(Path(directory.name) / "review.sqlite")
        self.trade_id = "btc-abcdef"
        self.ref = self.store.append_event(
            self.trade_id, "position_first_observed",
            {"symbol": "BTCUSD", "product_id": 1, "size": "1",
             "mark_price": "63000", "observed_at": "2026-11-19T00:00:00Z"},
            event_id="evt-abc")
        self.calls = []

    def test_one_paid_kimi_call_writes_only_candidates(self):
        calls = self.calls
        ref = self.ref
        class Client:
            def _call(self, url, *, body, timeout):
                calls.append((url, body))
                return {
                    "choices": [{"finish_reason": "stop", "message": {
                        "content": json.dumps({"insights": [{
                            "hypothesis": "Repeated entries may chase short-lived momentum",
                            "counterevidence": "A single snapshot cannot prove a pattern",
                            "applicable_when": "Only when recurring breakout evidence exists",
                            "confidence": 0.25,
                            "evidence_refs": [ref],
                        }]})}}],
                    "usage": {"total_tokens": 412},
                }
        reviewer = KimiLearningReviewer(self.store, client_factory=Client)
        result = reviewer.review(self.trade_id, "entry", "entry-btc-abcdef")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["lessons"], 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["model"], KIMI_REVIEW_MODEL)
        self.assertNotIn("orders", calls[0][1])
        self.assertEqual(self.store.fire_advisories(), [])
        self.assertEqual(len(self.store.lessons()), 1)
        self.assertEqual(reviewer.review(self.trade_id, "entry", "entry-btc-abcdef")["status"],
                         "already_reviewed_or_budget_exhausted")
        self.assertEqual(len(calls), 1)

    def test_provider_rejection_cannot_become_training_fact(self):
        class Client:
            def _call(inner, url, *, body, timeout):
                self.calls.append(body)
                return {"choices": [{"finish_reason": "stop",
                                     "message": {"content": json.dumps({
                                         "insights": [{
                                             "hypothesis": "Do not trust a fabricated reference",
                                             "counterevidence": "Evidence is missing",
                                             "applicable_when": "When an evidence ID exists",
                                             "confidence": 0.8,
                                             "evidence_refs": ["made-up-event"],
                                         }]
                                     })}}]}
        reviewer = KimiLearningReviewer(self.store, client_factory=Client)
        status = reviewer.review(self.trade_id, "exit", "exit-btc-abcdef")
        self.assertEqual(status["status"], "rejected")
        self.assertEqual(self.store.lessons(), [])
        self.assertEqual(self.store.fire_advisories(), [])
        reviewer.review(self.trade_id, "exit", "exit-btc-abcdef")
        self.assertEqual(len(self.calls), 1)

    def test_zero_evidence_never_spends(self):
        reviewer = KimiLearningReviewer(self.store,
                                        client_factory=lambda: self.fail("unexpected paid call"))
        self.assertEqual(
            reviewer.review("btc-other", "entry", "entry-btc-other")["status"],
            "no_evidence")


if __name__ == "__main__":
    unittest.main()
