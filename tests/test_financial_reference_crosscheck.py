"""Synthetic signed-fill reference triangulation without trade authorization."""
from copy import deepcopy
import unittest
from tradebot.fire_reconciliation import normalize_fill
from tradebot.financial_reference_crosscheck import crosscheck_foreign_fill_refs
from test_fire_reconciliation import Broker, BASE


class Reader:
    def __init__(self, fills, *, error=False):
        self.fills = fills
        self.error = error
        self.calls = []
    def _account_history(self, path, start, end):
        self.calls.append((path, start, end))
        if self.error:
            raise ValueError("private broker error")
        return deepcopy(self.fills)


class ReferenceCrosscheckTests(unittest.TestCase):
    def setup_case(self):
        broker = Broker()
        foreign = deepcopy(broker.fills[0])
        foreign["id"] = "unrelated-fill"
        foreign["order_id"] = 999
        posting = {"product_id":"27", "at_us":BASE + 15_000_000,
                   "type":"commission", "order_id":None,
                   "fill_id":"unrelated-fill"}
        owned = [normalize_fill(f) for f in broker.fills]
        return broker, foreign, posting, owned

    def check(self, reader, posting, owned):
        return crosscheck_foreign_fill_refs(
            reader, [posting], owned, ["100","101","102"], 27,
            BASE, BASE + 120_000_000)

    def test_valid_foreign_same_product_fill_still_blocks_accounting(self):
        broker, foreign, posting, owned = self.setup_case()
        reader = Reader(broker.fills + [foreign])
        r = self.check(reader, posting, owned)
        self.assertEqual(r["status"], "diagnostic_only_unresolved")
        self.assertEqual(r["matched_same_product_other_orders"], 1)
        self.assertTrue(r["external_signed_fill_history_consistent"])
        self.assertFalse(r["financial_attribution_verified"])
        self.assertFalse(r["safe_to_enable_fire"])
        self.assertEqual(reader.calls, [("/v2/fills", BASE, BASE+120_000_000)])

    def test_missing_reference_never_assumes_ownership(self):
        broker, foreign, posting, owned = self.setup_case()
        r = self.check(Reader(broker.fills), posting, owned)
        self.assertEqual(r["reference_not_found_in_signed_history"], 1)
        self.assertFalse(r["financial_attribution_verified"])

    def test_filtered_history_conflict_blocks_diagnostic(self):
        broker, foreign, posting, owned = self.setup_case()
        conflicting = deepcopy(broker.fills)
        conflicting[0]["price"] = "50000"
        r = self.check(Reader(conflicting), posting, owned)
        self.assertEqual(r["status"], "filtered_unfiltered_fill_conflict")
        self.assertFalse(r["external_signed_fill_history_consistent"])

    def test_signed_history_unavailable_is_sanitized(self):
        broker, foreign, posting, owned = self.setup_case()
        r = self.check(Reader([], error=True), posting, owned)
        self.assertEqual(r["status"], "signed_fill_crosscheck_unavailable")
        self.assertNotIn("private broker error", str(r))

    def test_unrelated_posting_does_not_fetch_more_history(self):
        broker, foreign, posting, owned = self.setup_case()
        posting["product_id"] = "999"
        reader = Reader(broker.fills)
        r = self.check(reader, posting, owned)
        self.assertEqual(r["overlap_reference_count"], 0)
        self.assertEqual(reader.calls, [])
