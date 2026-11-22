"""M09 single-trade read-only financial evidence phase triage (DEMO only).

Diagnoses the first failure stage that the ordinary reconciliation currently
summarizes as broker_evidence_or_ledger_unavailable. Never saves financial
evidence, touches the original reconciliation ledger, sends orders, invokes
models, or claims trade release. Only Delta India DEMO GET calls are possible.

This is a diagnostic, not a substitute for immutable, reviewed reconciliation.
"""
import argparse
from datetime import datetime, timedelta, timezone
from decimal import localcontext
import json
import os
from pathlib import Path
import re

from tradebot.delta import DeltaDemo, DEMO_API
from tradebot.fire_bracket_evidence import _saved, BracketEvidenceError, VALID_FIRE_ID
from tradebot.fire_inventory import read_inventory, _read_rows, InventoryEvidenceError
from tradebot.financial_reference_crosscheck import crosscheck_foreign_fill_refs
from tradebot.fire_reconciliation import (
    ReconciliationError, analyse, identifier, normalize_fill,
    normalize_posting, timestamp_us, unique, EXTERNAL, number,
)

MAX_AGE = timedelta(days=7)
MAX_TARGET_AGE = timedelta(days=60)
MIN_AGE = timedelta(minutes=10)
_REASON = re.compile(r"[a-z0-9_]{1,80}\Z")


def _safe_reason(exc, default):
    """Never publish remote API exceptions, broker payloads, or secrets."""
    if isinstance(exc, (ReconciliationError, BracketEvidenceError,
                        InventoryEvidenceError)):
        code = str(exc)
        if _REASON.fullmatch(code):
            return code
    return default



def _unattributed_wallet_hints(postings, fills, order_ids, product_id):
    """Explain ambiguous postings by redacted numerical crosschecks, NOT attribution.

    This classifier mirrors analyse()'s unattributed posting predicate.
    An amount matching a real fill is NOT evidence of transaction ownership;
    unrelated trades can have identical fees or cashflow. The analyser still
    fails closed and no broker, local receipt or financial ledger is mutated.
    """
    owned = set(order_ids)
    selected = [f for f in fills if f["order_id"] in owned]
    if not selected:
        return None
    first, last = selected[0]["at_us"], selected[-1]["at_us"]
    owned_fills = {f["id"] for f in selected}
    other = [f for f in fills if f["order_id"] not in owned]
    other_orders = {f["order_id"] for f in other}
    other_fills = {f["id"] for f in other}

    # Derive expected economics only from the same already-normalized fills
    # passed to the strict broker analyser. Never return any money amounts.
    expected_cashflow = sum(
        (-number(f["size"]) if f["side"] == "buy" else number(f["size"]))
        * number(f["price"]) * number(f["contract_value"])
        for f in selected
    )
    expected_fee = -sum((number(f["commission"]) for f in selected), number(0))
    selected_fee_amounts = {-number(f["commission"]) for f in selected}
    other_fee_amounts = {-number(f["commission"]) for f in other}
    final_funding = selected[-1]["realized_funding"]
    expected_funding = number(final_funding) if final_funding is not None else None

    categories, comparisons = [], []
    for p in postings:
        if p["type"] in EXTERNAL:
            continue
        oid, fid = p["order_id"], p["fill_id"]
        linked = oid in owned or fid in owned_fills
        within = first <= p["at_us"] <= last
        same_product = p["product_id"] == str(product_id)
        if linked or (same_product and within):
            continue
        if p["at_us"] < first or not (same_product or p["product_id"] is None):
            continue
        if (oid in other_orders or fid in other_fills) and not within:
            continue
        categories.append({
            "product_scope": "same_product" if same_product else "account_unscoped",
            "timing": "within_position" if within else "after_last_fill",
            "order_reference": "present" if oid is not None else "absent",
            "fill_reference": "present" if fid is not None else "absent",
            "posting_kind": p["type"] if p["type"] in
                            ("cashflow", "commission", "funding") else "other",
        })
        if len(comparisons) < 5:
            amount = number(p["amount"])
            kind = p["type"]
            comparisons.append({
                "matches_selected_total_cashflow_exact":
                    amount == expected_cashflow if kind == "cashflow" else None,
                "matches_selected_total_commission_exact":
                    amount == expected_fee if kind == "commission" else None,
                "matches_selected_single_fill_commission_exact":
                    amount in selected_fee_amounts if kind == "commission" else None,
                "matches_other_same_product_fill_commission_exact":
                    amount in other_fee_amounts if kind == "commission" else None,
                "matches_selected_final_funding_exact":
                    (amount == expected_funding if expected_funding is not None
                     else None) if kind == "funding" else None,
            })
    if not categories:
        return None
    return {
        "count": len(categories),
        "examples": categories[:5],
        "examples_truncated": len(categories) > 5,
        "amount_consistency_clues": comparisons,
        "unowned_same_product_fills_after_last_fill": sum(
            f["at_us"] > last for f in other),
        "other_product_fill_history_checked": False,
        "amount_matches_prove_broker_attribution": False,
    }


def _wallet_reference_linkage(raw_postings, normalized_postings, fills, owned_orders, product_id):
    """Count actual provider-reference joins; no metadata values leave memory.

    This records evidence identity matches, not a wallet reconciliation.
    Cashflow remains unowned unless the strict analyser proves it separately.
    """
    selected = [f for f in fills if f["order_id"] in set(owned_orders)]
    if not selected:
        return None
    final_fill_time = max(f["at_us"] for f in selected)
    owned_fill_ids = {f["id"] for f in selected}
    normalized = {p["id"]: p for p in normalized_postings}
    names_allowed = frozenset({
        "order_id", "fill_id", "fill_uuid", "order_uuid", "trade_id",
        "trade_uuid", "position_id", "reference_id", "source_id",
        "cashflow_id", "settlement_id", "last_fill_uuid",
    })
    report = {
        "commission_fill_uuid_matched_signed_owned_fill": 0,
        "commission_fill_uuid_not_matched_owned_fill": 0,
        "delayed_cashflow_without_proven_order_or_fill_reference": 0,
        "delayed_cashflow_candidate_reference_field_names": [],
        "delayed_cashflow_has_other_metadata_fields": False,
        "financial_attribution_verified": False,
        "all_unmatched_wallet_transactions_resolved": False,
        "raw_broker_values_exposed": False,
    }
    candidate_fields = set()
    visited = set()
    for row in raw_postings:
        pid = identifier(row.get("id"))
        if pid in visited:
            continue
        visited.add(pid)
        p = normalized.get(pid)
        if p is None:
            raise ReconciliationError("wallet_reference_identity_unverified")
        meta = row.get("meta_data") or {}
        if not isinstance(meta, dict):
            raise ReconciliationError("invalid_posting_metadata")
        # Only count commissions in the *original unresolved post-fill*
        # period for this product. Earlier wallet commissions are not
        # necessarily expected to belong to this one receipt. Counting all
        # of them generated misleading 0/4 operator evidence in Nov 2026.
        if (p["type"] == "commission"
                and p["product_id"] == str(product_id)
                and p["at_us"] > final_fill_time
                and (row.get("fill_uuid") is not None
                     or meta.get("fill_uuid") is not None)):
            if p["fill_id"] in owned_fill_ids:
                report["commission_fill_uuid_matched_signed_owned_fill"] += 1
            else:
                report["commission_fill_uuid_not_matched_owned_fill"] += 1
        if (p["type"] == "cashflow"
                and p["product_id"] == str(product_id)
                and p["at_us"] > final_fill_time
                and p["order_id"] is None and p["fill_id"] is None):
            report["delayed_cashflow_without_proven_order_or_fill_reference"] += 1
            candidate_fields.update((set(row) | set(meta)) & names_allowed)
            if set(meta) - names_allowed:
                report["delayed_cashflow_has_other_metadata_fields"] = True
    report["delayed_cashflow_candidate_reference_field_names"] = sorted(candidate_fields)
    return report


def _overlapping_posting_hints(postings, fills, owned_orders, product_id):
    """Classify conflicting in-position references without revealing IDs.

    Mirrors the *specific* strict analyser guard for same-product
    within-position postings that point to neither a selected owned order
    nor one of its signed fills. Counts never constitute attribution.
    """
    owned = set(owned_orders)
    selected = [f for f in fills if f["order_id"] in owned]
    if not selected:
        return None
    first = min(f["at_us"] for f in selected)
    last = max(f["at_us"] for f in selected)
    owned_fills = {f["id"] for f in selected}
    other_fills = {f["id"] for f in fills if f["order_id"] not in owned}
    out = {
        "same_product_in_position_unowned_reference_count": 0,
        "kinds": {"commission": 0, "cashflow": 0, "funding": 0, "other": 0},
        "order_reference_present": 0,
        "fill_reference_present": 0,
        "fill_reference_in_other_signed_fill": 0,
        "fill_reference_not_in_signed_fill_window": 0,
        "wallet_ownership_proven": False,
        "can_remove_blocker": False,
        "raw_broker_values_exposed": False,
    }
    for posting in postings:
        if posting["type"] in EXTERNAL:
            continue
        if posting["product_id"] != str(product_id):
            continue
        if not first <= posting["at_us"] <= last:
            continue
        order_ref, fill_ref = posting["order_id"], posting["fill_id"]
        if order_ref in owned or fill_ref in owned_fills:
            continue
        if order_ref is None and fill_ref is None:
            continue
        out["same_product_in_position_unowned_reference_count"] += 1
        kind = posting["type"] if posting["type"] in out["kinds"] else "other"
        out["kinds"][kind] += 1
        out["order_reference_present"] += order_ref is not None
        out["fill_reference_present"] += fill_ref is not None
        out["fill_reference_in_other_signed_fill"] += fill_ref in other_fills
        out["fill_reference_not_in_signed_fill_window"] += (
            fill_ref is not None and fill_ref not in other_fills
            and fill_ref not in owned_fills
        )
    return out


def _base_report():
    return {
        "environment": "delta-india-demo",
        "mode": "authenticated_get_only_diagnostic",
        "status": "blocked",
        "stage": "preflight",
        "reason": "not_started",
        "stages_passed": [],
        "eligible_recent_btc_receipts": 0,
        "local_flat_btc_receipts": 0,
        "historical_cutoff_applied": False,
        "locally_unverified_bracket_receipts": 0,
        "authenticated_order_gets": 0,
        "fill_count": None,
        "wallet_posting_count": None,
        "financial_reconciliation_status": "awaiting_complete_broker_evidence",
        "is_net_realized_pnl": False,
        "funding_reconciled": False,
        "cashflow_and_commission_consistency_proven_in_memory": False,
        "unattributed_wallet_posting_diagnostic": None,
        "wallet_reference_linkage_diagnostic": None,
        "overlapping_wallet_posting_diagnostic": None,
        "account_wide_fill_reference_crosscheck": None,
        "original_ledger_mutations": False,
        "temporary_ledger_mutations": False,
        "broker_order_mutations": False,
        "ai_calls": 0,
        "trade_authorized": False,
        "safe_to_enable_fire": False,
        "ready_for_unattended_trading": False,
    }


def probe_single_recent_btc(exchange, data_dir, *, now=None, fire_id=None):
    """Inspect one verified BTC receipt using a bounded DEMO GET history.

    No explicit ID: original latest-recent behavior. With a valid explicit ID,
    allow an older existing receipt (<=60 days); never broaden the broker query
    beyond seven days from the original request, even when rerun much later.
    The resulting observation is still not a durable financial attestation.
    """
    out = _base_report()

    def block(stage, reason):
        out["stage"] = stage
        out["reason"] = reason
        return out

    if fire_id is not None and (type(fire_id) is not str
                                or VALID_FIRE_ID.fullmatch(fire_id) is None):
        return block("preflight", "invalid_requested_fire_id")
    if (getattr(exchange, "base_url", None) != DEMO_API
            or getattr(exchange, "allow_orders", None) is not False):
        return block("preflight", "read_only_delta_demo_required")
    now = now or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        return block("preflight", "trusted_utc_time_required")

    root = Path(data_dir)
    try:
        inventory = read_inventory(root, limit=200)
        if inventory["entries_truncated"]:
            return block("receipt_selection", "local_inventory_truncated")
        rows = _read_rows(
            root / "fire-ops.sqlite",
            "SELECT press,created_at,updated_at,status,result FROM fire_requests",
        )
        if rows is None:
            return block("receipt_selection", "original_btc_receipts_missing")
        by_id = {r[0]: r for r in rows}
    except InventoryEvidenceError as exc:
        return block("receipt_selection", _safe_reason(exc, "local_inventory_unavailable"))
    except Exception:
        return block("receipt_selection", "local_inventory_unavailable")

    btc = [item for item in inventory["entries"]
           if item["symbol"] == "BTCUSD"
           and item["category"] == "locally_reported_flat"]
    out["local_flat_btc_receipts"] = len(btc)
    selected = None
    for item in btc:
        if fire_id is not None and item["fire_id"] != fire_id:
            continue
        if item["local_financial_report_present"]:
            continue
        try:
            t = datetime.fromisoformat(item["created_at"]).astimezone(timezone.utc)
            age = now.astimezone(timezone.utc) - t
        except (ValueError, TypeError, OverflowError):
            return block("receipt_selection", "invalid_receipt_timestamp")
        if not MIN_AGE < age < (MAX_AGE if fire_id is None else MAX_TARGET_AGE):
            continue
        try:
            saved, fingerprint = _saved(root, "BTCUSD", item["fire_id"])
        except BracketEvidenceError:
            out["locally_unverified_bracket_receipts"] += 1
            continue
        out["eligible_recent_btc_receipts"] += 1
        if selected is None:
            selected = (item, saved, fingerprint)

    if selected is None:
        return block("receipt_selection",
                     "requested_receipt_not_eligible" if fire_id is not None
                     else "no_recent_local_bracket_candidate")

    item, saved, fingerprint = selected
    row = by_id.get(item["fire_id"])
    if row is None:
        return block("receipt_selection", "original_btc_receipt_changed")
    try:
        payload = json.loads(row[4])
        if type(payload) is not dict:
            return block("receipt_selection", "original_btc_receipt_invalid")
        trade = dict(payload, id=item["fire_id"], created_at=row[1], status=row[3])
        start_us = timestamp_us(trade["created_at"])
        observed_end_us = timestamp_us(now.astimezone(timezone.utc).isoformat())
        # A 60-day-old receipt must NOT silently turn into a 60-day account
        # history request. Seven days is the original provenance boundary;
        # any late settlement outside that window remains unresolved.
        max_end_us = start_us + 7 * 86400 * 1_000_000 - 1
        end_us = min(observed_end_us, max_end_us)
        out["historical_cutoff_applied"] = end_us != observed_end_us
        if not 0 < end_us - start_us < 7 * 86400 * 1_000_000:
            return block("receipt_selection", "bounded_history_window_invalid")
    except (ValueError, ReconciliationError, TypeError):
        return block("receipt_selection", "original_btc_receipt_invalid")
    out["stages_passed"].append("receipt_selection")

    try:
        response = exchange._request("GET", "/v2/products/BTCUSD")
        product = response["result"]
        if not isinstance(product, dict):
            return block("product", "broker_product_response_invalid")
        pid = product["id"]
        if type(pid) is not int or pid <= 0 or product.get("symbol") != "BTCUSD":
            return block("product", "broker_product_identity_mismatch")
    except Exception:
        return block("product", "broker_product_get_unavailable")
    out["stages_passed"].append("product")

    # Saved IDs are validated decimal strings by _saved before broker use.
    order_ids = [saved[k] for k in (
        "parent", "stop_loss_order", "take_profit_order")]
    orders = {}
    for order_id in order_ids:
        try:
            response = exchange._request(
                "GET", "/v2/orders/" + order_id, auth=True)
            row = response["result"]
            if not isinstance(row, dict) or str(row.get("id")) != order_id:
                return block("orders", "broker_order_identity_unverified")
            orders[order_id] = row
            out["authenticated_order_gets"] += 1
        except Exception:
            return block("orders", "broker_order_get_unavailable")
    out["stages_passed"].append("orders")

    try:
        raw_fills = exchange.product_fills(
            pid, start_time_us=start_us, end_time_us=end_us)
        if not isinstance(raw_fills, list):
            return block("fills", "broker_fill_window_unverified")
    except Exception:
        return block("fills", "broker_fill_history_unavailable")
    out["stages_passed"].append("fills")

    try:
        fills = unique([normalize_fill(row) for row in raw_fills])
    except Exception as exc:
        return block("fill_normalization", _safe_reason(
            exc, "broker_fill_schema_unverified"))
    out["fill_count"] = len(fills)
    out["stages_passed"].append("fill_normalization")

    try:
        raw_postings = exchange.wallet_postings(start_us, end_us)
        if not isinstance(raw_postings, list):
            return block("wallet_postings", "broker_wallet_window_unverified")
    except Exception:
        return block("wallet_postings", "broker_wallet_history_unavailable")
    out["stages_passed"].append("wallet_postings")

    try:
        postings = unique([normalize_posting(row) for row in raw_postings])
    except Exception as exc:
        return block("wallet_normalization", _safe_reason(
            exc, "broker_wallet_schema_unverified"))
    out["wallet_posting_count"] = len(postings)
    out["stages_passed"].append("wallet_normalization")

    # One-pass provider-reference inventory on the SAME original signed
    # bounded broker window. No extra GET, persistence, or raw value logging.
    try:
        out["wallet_reference_linkage_diagnostic"] = _wallet_reference_linkage(
            raw_postings, postings, fills, order_ids, pid)
    except Exception:
        # A supplementary diagnostic cannot override strict accounting.
        out["wallet_reference_linkage_diagnostic"] = None

    try:
        with localcontext() as ctx:
            ctx.prec = 128
            result = analyse(
                "BTCUSD", trade, product, orders, fills, postings, start_us, end_us)
    except Exception as exc:
        reason = _safe_reason(exc, "financial_analysis_unverified")
        # The analyser emits this code only AFTER all broker cashflow and
        # commission postings match the signed fills, and BEFORE net P&L.
        # This is diagnostic-only, NOT a durable financial review.
        if isinstance(exc, ReconciliationError) and reason == "missing_broker_funding_total":
            out["cashflow_and_commission_consistency_proven_in_memory"] = True
        if isinstance(exc, ReconciliationError) and reason == "unattributed_wallet_posting":
            try:
                out["unattributed_wallet_posting_diagnostic"] = _unattributed_wallet_hints(
                    postings, fills, order_ids, pid)
            except Exception:
                # Never disclose broker data or change the original blocker if
                # the supplementary diagnostic itself cannot classify it.
                pass
        if isinstance(exc, ReconciliationError) and reason == "overlapping_external_postings":
            try:
                out["overlapping_wallet_posting_diagnostic"] = _overlapping_posting_hints(
                    postings, fills, order_ids, pid)
            except Exception:
                # Supplementary classification is never an accounting waiver.
                pass
            # Account-wide signed GET may identify a foreign fill reference
            # omitted by a product filter. Diagnosis never changes analyse().
            try:
                out["account_wide_fill_reference_crosscheck"] = (
                    crosscheck_foreign_fill_refs(
                        exchange, postings, fills, order_ids, pid, start_us, end_us))
            except Exception:
                pass
        return block("financial_analysis", reason)
    out["cashflow_and_commission_consistency_proven_in_memory"] = True
    out["stages_passed"].append("financial_analysis")

    # A concurrent receipt rewrite/replacement cannot be treated as a clean
    # match, even though no original file was modified by this diagnostic.
    try:
        _, after = _saved(root, "BTCUSD", item["fire_id"])
        if after != fingerprint:
            return block("local_evidence_stability", "original_btc_receipt_changed")
    except Exception:
        return block("local_evidence_stability", "original_btc_receipt_unavailable")
    out["stages_passed"].append("local_evidence_stability")

    if result.get("is_net_realized_pnl") is not True:
        return block("financial_analysis", "broker_financial_evidence_unverified")

    out["status"] = "provisional_read_only_financial_analysis_complete"
    out["stage"] = "complete"
    out["reason"] = "not_persisted_not_current_trade_authority"
    # No money amounts, account IDs or immutable-source evidence are exported.
    # This is NOT the durable financial reconciliation release milestone.
    out["financial_reconciliation_status"] = "analysis_only_not_durable_report"
    out["funding_reconciled"] = True
    out["is_net_realized_pnl"] = False
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--fire-id", default=None,
                        help="Optional original completed BTC FIRE ID (32 lowercase hex)")
    args = parser.parse_args(argv)
    exchange = DeltaDemo(
        api_key=os.environ.get("DELTA_DEMO_API_KEY", ""),
        api_secret=os.environ.get("DELTA_DEMO_API_SECRET", ""),
        allow_orders=False,
    )
    result = probe_single_recent_btc(exchange, args.data_dir, fire_id=args.fire_id)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == (
        "provisional_read_only_financial_analysis_complete") else 2


if __name__ == "__main__":
    raise SystemExit(main())
