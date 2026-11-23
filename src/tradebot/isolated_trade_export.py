"""Read-only BTCUSD/XAUTUSD isolated-demo receipts for operator-led review.

Never infer P&L from a closed position; manual labels remain operator-owned.
No broker/model calls, account mutations or shared-main-account reads.
"""
import argparse
import csv
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from contextlib import closing

LEDGERS = {"BTCUSD": ("btc-isolated", "fire-ops.sqlite"),
           "XAUTUSD": ("gold-isolated", "fire-xaut.sqlite")}
FIELDS = ("symbol account_scope fire_id created_at_utc updated_at_utc status "
          "reason_code model direction contracts leverage entry_fill_price "
          "entry_fill_time_utc best_bid best_ask stop_loss take_profit "
          "broker_order_id orders_submitted protection_verified "
          "liquidation_verified estimated_net_rr thesis market_indicators_json "
          "quality_warnings_json broker_verified_net_pnl_usd "
          "manual_review_label manual_notes").split()


def _str(x):
    return "" if x is None else str(x)


def read_account(data_root, symbol):
    if symbol not in LEDGERS:
        raise ValueError("Unknown isolated account")
    directory, filename = LEDGERS[symbol]
    root = Path(data_root)
    child = root / directory
    path = child / filename
    if (root.is_symlink() or child.is_symlink() or path.is_symlink()
            or not child.is_dir() or not path.is_file()):
        raise ValueError("Missing or untrusted isolated ledger: " + symbol)
    with closing(sqlite3.connect(path.absolute().as_uri() + "?mode=ro",
                                 uri=True, timeout=5)) as db:
        db.execute("PRAGMA query_only=ON")
        records = db.execute(
            "SELECT press,created_at,updated_at,status,result FROM "
            "fire_requests ORDER BY created_at,press").fetchall()
    rows = []
    for press, created, updated, status, result in records:
        if not isinstance(press, str) or not re.fullmatch(r"[0-9a-f]{32}", press):
            raise ValueError("Invalid FIRE identity")
        try:
            d = json.loads(result)
        except (TypeError, ValueError) as exc:
            raise ValueError("Malformed FIRE result") from exc
        if not isinstance(d, dict):
            raise ValueError("Invalid FIRE result")
        entry = d.get("entry") if isinstance(d.get("entry"), dict) else {}
        quote = d.get("decision_quote") if isinstance(d.get("decision_quote"), dict) else {}
        risk = d.get("risk_assessment") if isinstance(d.get("risk_assessment"), dict) else {}
        signals = d.get("indicators") if isinstance(d.get("indicators"), dict) else {}
        warnings = risk.get("quality_warnings")
        row = dict.fromkeys(FIELDS, "")
        row.update(symbol=symbol, account_scope=directory, fire_id=press,
                   created_at_utc=_str(created), updated_at_utc=_str(updated),
                   status=_str(status))
        for dest, source in (("reason_code","reason_code"),("model","model"),
                             ("direction","direction"),("contracts","contracts"),
                             ("leverage","selected_leverage"),("stop_loss","stop_loss"),
                             ("take_profit","take_profit"),
                             ("broker_order_id","broker_order_id"),
                             ("orders_submitted","orders_submitted"),
                             ("protection_verified","protection_verified"),
                             ("liquidation_verified","liquidation_verified"),
                             ("thesis","thesis")):
            row[dest] = _str(d.get(source))
        row.update(entry_fill_price=_str(entry.get("price")),
                   entry_fill_time_utc=_str(entry.get("at")),
                   best_bid=_str(quote.get("best_bid")),
                   best_ask=_str(quote.get("best_ask")),
                   estimated_net_rr=_str(risk.get("expected_net_reward_risk")),
                   market_indicators_json=json.dumps(signals, sort_keys=True),
                   quality_warnings_json=json.dumps(
                       warnings if isinstance(warnings, list) else []))
        # P&L and operator classifications are intentionally blank.
        rows.append(row)
    return rows


def collect(data_root, symbol="BOTH"):
    symbols = LEDGERS if symbol == "BOTH" else (symbol,)
    if any(x not in LEDGERS for x in symbols):
        raise ValueError("Unknown isolated account")
    rows = [r for x in symbols for r in read_account(data_root, x)]
    return sorted(rows, key=lambda r: (r["created_at_utc"], r["symbol"], r["fire_id"]))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Export isolated DEMO trade attempts without classifying them.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--symbol", choices=("BOTH", "BTCUSD", "XAUTUSD"),
                        default="BOTH")
    parser.add_argument("--output", help="New private CSV path (never overwritten)")
    args = parser.parse_args(argv)
    rows = collect(args.data_dir, args.symbol)
    output = None
    try:
        if args.output:
            flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL
                     | getattr(os, "O_NOFOLLOW", 0))
            fd = os.open(args.output, flags, 0o600)
            output = os.fdopen(fd, "w", encoding="utf-8", newline="")
        else:
            output = sys.stdout
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            # Prevent AI-generated prose from becoming executable spreadsheet formulae.
            for key in ("thesis", "model", "market_indicators_json",
                        "quality_warnings_json"):
                if row[key].startswith(("=", "+", "-", "@", "\t", "\r")):
                    row[key] = "'" + row[key]
            writer.writerow(row)
    finally:
        if args.output and output:
            output.close()
    print("exported_attempts=" + str(len(rows)) + " symbol=" + args.symbol,
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())