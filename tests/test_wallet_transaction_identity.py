"""Offline safeguards for Delta DEMO wallet UUID IDs vs documented id fields.

Never contacts Delta, touches live SQLite, or grants trading permissions.
"""
import unittest

from tradebot.delta import DeltaDemo, DeltaError
from tradebot.fire_reconciliation import normalize_posting

WALLET = "/v2/wallet/transactions"
FILLS = "/v2/fills"
UUID_A = "123e4567-e89b-42d3-a456-426614174000"
UUID_B = "123e4567-e89b-42d3-a456-426614174001"


def wallet_record(**kw):
    row = dict(uuid=UUID_A, created_at="2026-11-22T00:00:00+00:00",
               asset_symbol="USD", amount="-0.01",
               transaction_type="commission", product_id=27,
               meta_data={"order_id": 100})
    row.update(kw)
    return row


class SimulatedDemo(DeltaDemo):
    def __init__(self, responses):
        super().__init__(allow_orders=False)
        self.responses = list(responses)
        self.calls = []

    def _request(self, method, path, *, params=None, auth=False, **unused):
        self.calls.append((method, path, dict(params or {}), auth))
        if method != "GET" or not auth:
            raise AssertionError("Broker call must be authenticated GET only")
        if not self.responses:
            raise AssertionError("Unexpected additional broker request")
        return self.responses.pop(0)


def page(records, after=None):
    return {"success": True, "result": records,
            "meta": {"after": after, "before": None}}


class WalletTransactionUUIDTests(unittest.TestCase):
    def read(self, responses, *, endpoint=WALLET):
        broker = SimulatedDemo(responses)
        result = broker._account_history(endpoint, 10**15, 10**15 + 100)
        self.assertTrue(all(method == "GET" and auth
                            for method, _, _, auth in broker.calls))
        return result, broker

    def test_wallet_uuid_only_is_stable_broker_identity(self):
        out, broker = self.read([page([wallet_record()])])
        self.assertEqual(out[0]["id"], UUID_A)
        self.assertEqual(out[0]["uuid"], UUID_A)
        normalized = normalize_posting(out[0])
        self.assertEqual(normalized["id"], UUID_A)
        self.assertEqual(len(broker.calls), 1)
        self.assertEqual(broker.calls[0][1], WALLET)
        self.assertFalse(broker.allow_orders)

    def test_undashed_broker_uuid_is_normalized_not_generated(self):
        out, _ = self.read([page([wallet_record(uuid=UUID_A.replace("-", ""))])])
        self.assertEqual(out[0]["id"], UUID_A)

    def test_numeric_id_existing_behavior_unchanged(self):
        out, _ = self.read([page([{"id": 4567, "amount": "1"}])])
        self.assertEqual(out[0]["id"], 4567)
        self.assertNotIn("uuid", out[0])

    def test_existing_explicit_id_takes_precedence_over_uuid(self):
        out, _ = self.read([page([{"id": 4567, "uuid": "not-uuid"}])])
        self.assertEqual(out[0]["id"], 4567)

    def test_missing_or_malformed_uuid_cannot_fabricate_id(self):
        examples = [
            {"amount": "1"}, {"uuid": None}, {"uuid": 123},
            {"uuid": ""}, {"uuid": "invalid-uuid"},
            {"uuid": "00000000-0000-0000-0000-00000000000G"},
            {"uuid": " " + UUID_A + " "},
            {"uuid": UUID_A[:8] + "-" + UUID_A[9:]},
        ]
        for row in examples:
            with self.subTest(row=row):
                with self.assertRaises(DeltaError):
                    self.read([page([row])])

    def test_duplicated_uuid_same_row_across_pages_deduplicated(self):
        row = wallet_record()
        out, broker = self.read([
            page([row], after="opaque-next-page"),
            page([row], after=None),
        ])
        self.assertEqual(len(out), 1)
        self.assertEqual(len(broker.calls), 2)
        self.assertEqual(broker.calls[1][2]["after"], "opaque-next-page")

    def test_same_uuid_with_conflicting_amount_fails_closed(self):
        first = wallet_record()
        changed = dict(first, amount="-500")
        with self.assertRaisesRegex(DeltaError,
                                    "Inconsistent account history ID"):
            self.read([
                page([first], after="opaque-next-page"),
                page([changed]),
            ])

    def test_two_distinct_uuid_records_preserved(self):
        out, _ = self.read([page([wallet_record(),
                                  wallet_record(uuid=UUID_B)])])
        self.assertEqual({row["id"] for row in out}, {UUID_A, UUID_B})

    def test_malformed_cursor_still_blocks_wallet(self):
        with self.assertRaisesRegex(DeltaError,
                                    "Invalid account history cursor"):
            self.read([page([wallet_record()], after=12)])

    def test_missing_meta_cursor_still_blocks_wallet(self):
        with self.assertRaisesRegex(DeltaError,
                                    "Invalid account history page"):
            self.read([{"result": [wallet_record()],
                        "meta": {"before": None}}])

    def test_uuid_fallback_does_not_relax_fill_identifier_check(self):
        with self.assertRaisesRegex(DeltaError,
                                    "Missing account history ID"):
            self.read([page([{"uuid": UUID_A}])], endpoint=FILLS)

    def test_no_raw_broker_financial_data_recorded(self):
        broker = SimulatedDemo([page([wallet_record()])])
        out = broker.wallet_postings(10**15, 10**15 + 100)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], UUID_A)
        self.assertEqual(len(broker.calls), 1)
        self.assertEqual(broker.calls[0][1], WALLET)


if __name__ == "__main__":
    unittest.main()
