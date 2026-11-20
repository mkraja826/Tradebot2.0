from datetime import datetime, timedelta, timezone
from email.message import Message
from email.utils import format_datetime
import io
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from equity_fixtures import receipt_for
from tradebot.delta import DeltaDemo, DeltaReadError
from tradebot.equity_receipt import EquityReadError, validate_receipt
from tradebot.portfolio_equity_guard import PortfolioEquityGuard, EquityRiskError

NOW = datetime(2026, 11, 23, 0, 1, tzinfo=timezone.utc)


class ReceiptTests(unittest.TestCase):
    def test_fresh_read_accepted_in_utc_and_ist(self):
        for now in (NOW, NOW.astimezone(timezone(timedelta(hours=5, minutes=30)))):
            self.assertEqual(validate_receipt("1000", receipt_for(at=now), now=now), NOW)

    def test_bad_evidence_fails_closed(self):
        r = receipt_for(at=NOW)
        cases = [
            ({}, "equity_read_receipt_missing"),
            ({**r, "equity_usd": "999"}, "equity_read_value_mismatch"),
            ({**r, "equity_usd": "NaN"}, "equity_read_value_mismatch"),
            ({**r, "received_us": True}, "equity_read_receipt_invalid"),
            ({**r, "response_sha256": "token=secret"}, "equity_read_receipt_invalid"),
            ({**r, "api_key": "secret"}, "equity_read_receipt_invalid"),
            ({**r, "server_date_us": r["server_date_us"] - 60_000_000}, "broker_clock_or_stale_response"),
            ({**r, "server_date_us": r["server_date_us"] + 60_000_000}, "broker_clock_or_stale_response"),
            ({**r, "cache_age_seconds": 1}, "broker_equity_response_cached"),
            ({**r, "cache_age_seconds": -1}, "broker_equity_response_cached"),
            ({**r, "elapsed_us": 2_000_000}, "system_clock_jump"),
            ({**r, "request_started_us": r["received_us"] + 1}, "system_clock_jump"),
            ({**r, "request_started_us": r["received_us"] - 11_000_000,
              "elapsed_us": 11_000_000}, "broker_equity_read_slow"),
        ]
        for receipt, code in cases:
            with self.subTest(code=code), self.assertRaisesRegex(EquityReadError, code):
                validate_receipt("1000", receipt, now=NOW)

    def test_stale_or_future_receipt_is_not_refreshed_by_reuse(self):
        with self.assertRaisesRegex(EquityReadError, "stale"):
            validate_receipt("1000", receipt_for(at=NOW), now=NOW + timedelta(seconds=31))
        with self.assertRaisesRegex(EquityReadError, "system_clock_jump"):
            validate_receipt("1000", receipt_for(at=NOW), now=NOW - timedelta(seconds=1))

    def test_midnight_straddle_cannot_create_a_new_opening(self):
        at = NOW.replace(minute=0, microsecond=100000)
        r = receipt_for(at=at)
        r.update(request_started_us=r["received_us"] - 200000, elapsed_us=200000)
        with self.assertRaisesRegex(EquityReadError, "boundary_ambiguous"):
            validate_receipt("1000", r, now=at)

    def test_broker_date_on_previous_day_is_ambiguous_even_within_clock_tolerance(self):
        at = NOW.replace(minute=0, second=1)
        r = receipt_for(at=at)
        r["server_date_us"] -= 2_000_000
        with self.assertRaisesRegex(EquityReadError, "boundary_ambiguous"):
            validate_receipt("1000", r, now=at)

    def test_original_evidence_and_receipts_immutable_and_duplicate_safe(self):
        with TemporaryDirectory() as tmp:
            guard = PortfolioEquityGuard(Path(tmp) / "risk.sqlite")
            r = receipt_for(at=NOW)
            self.assertTrue(guard.require_verified_read("1000", r, now=NOW)["approved"])
            guard.require_verified_read("1000", r, now=NOW)
            with sqlite3.connect(guard.path) as db:
                for table in ("equity_evidence", "equity_read_receipts"):
                    self.assertEqual(db.execute(f"SELECT count(*) FROM {table}").fetchone()[0], 1)
                    with self.assertRaises(sqlite3.IntegrityError):
                        db.execute(f"DELETE FROM {table}")
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute("UPDATE equity_read_receipts SET receipt='{}'")
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute("INSERT OR REPLACE INTO equity_evidence VALUES (?,?,'delta_demo_signed_wallet')",
                               (r["received_us"], "500"))
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute("INSERT OR REPLACE INTO equity_read_receipts VALUES (?,?)",
                               (r["received_us"], "{}"))
            with self.assertRaisesRegex(EquityRiskError, "Conflicting"):
                guard.observe_verified_read("1000", {**r, "response_sha256": "a" * 64}, now=NOW)

    def test_no_retroactive_receipt_or_out_of_order_insert(self):
        with TemporaryDirectory() as tmp:
            guard = PortfolioEquityGuard(Path(tmp) / "risk.sqlite")
            guard.observe("1000", at=NOW)
            with self.assertRaisesRegex(EquityRiskError, "retroactively"):
                guard.observe_verified_read("1000", receipt_for(at=NOW), now=NOW)
            with self.assertRaisesRegex(EquityRiskError, "out_of_order"):
                guard.observe("1000", at=NOW - timedelta(seconds=1))

    def test_no_invented_peak_after_watermark_loss(self):
        with TemporaryDirectory() as tmp:
            guard = PortfolioEquityGuard(Path(tmp) / "risk.sqlite")
            guard.observe("1000", at=NOW)
            with sqlite3.connect(guard.path) as db:
                db.execute("DELETE FROM equity_watermark")
            with self.assertRaisesRegex(EquityRiskError, "watermark_missing"):
                PortfolioEquityGuard(guard.path).observe("900", at=NOW + timedelta(minutes=1))
            with sqlite3.connect(guard.path) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM equity_watermark").fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT count(*) FROM equity_evidence").fetchone()[0], 1)


class TransportTests(unittest.TestCase):
    def response(self, *, date=True, age="0"):
        r = io.BytesIO(json.dumps({"success": True, "result": [], "meta": {"net_equity": "1000"},
                                  "_wallet_read_receipt": {"source": "untrusted_body"}}).encode())
        r.headers = Message()
        if date:
            r.headers["Date"] = format_datetime(datetime.now(timezone.utc), usegmt=True)
        r.headers["Age"] = age
        return r

    def test_single_signed_get_has_safe_transport_receipt(self):
        with patch("tradebot.delta.urlopen", return_value=self.response()) as request:
            wallet = DeltaDemo("test-key", "test-secret").wallet_balances()
        req = request.call_args.args[0]
        self.assertEqual(req.method, "GET")
        self.assertIn("cdn-ind.testnet.deltaex.org/v2/wallet/balances", req.full_url)
        self.assertEqual(req.get_header("Api-key"), "test-key")
        self.assertIn("no-store", req.get_header("Cache-control"))
        validate_receipt(wallet["meta"]["net_equity"], wallet["equity_read_receipt"])
        self.assertNotIn("test-secret", json.dumps(wallet))
        self.assertNotIn("test-key", json.dumps(wallet))
        self.assertEqual(request.call_count, 1)

    def test_missing_date_is_not_assumed_fresh(self):
        with patch("tradebot.delta.urlopen", return_value=self.response(date=False)):
            wallet = DeltaDemo("key", "secret").wallet_balances()
        self.assertEqual(wallet["meta"]["net_equity"], "1000")  # existing read-only consumers
        with self.assertRaisesRegex(EquityReadError, "broker_time_evidence_unavailable"):
            validate_receipt("1000", wallet["equity_read_receipt"])

    def test_timeout_and_auth_failures_are_sanitized_and_never_retried(self):
        cases = [(URLError("secret payload"), "broker_equity_unavailable"),
                 (TimeoutError("secret payload"), "broker_equity_unavailable"),
                 (HTTPError("https://example.invalid/?secret", 401, "secret", {}, None),
                  "broker_authentication_failed")]
        for error, code in cases:
            with patch("tradebot.delta.urlopen", side_effect=error) as request:
                with self.assertRaises(DeltaReadError) as caught:
                    DeltaDemo("key", "secret").wallet_balances()
                self.assertEqual(str(caught.exception), code)
                self.assertEqual(request.call_count, 1)
