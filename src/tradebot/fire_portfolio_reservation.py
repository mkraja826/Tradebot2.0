"""Durable single-entry reservation shared by BTCUSD and XAUTUSD FIRE.

This is a cross-FIRE concurrency guard, NOT a full portfolio risk engine.
It cannot discover third-party manual orders or unsupported market exposure;
broker/portfolio-level reconciliation must remain mandatory independently.
"""
from contextlib import closing
from pathlib import Path
from uuid import UUID
import os
import sqlite3

TERMINAL_SAFE = frozenset({
    "rejected_no_order", "aborted_flat", "flat_verified",
    "cancelled_flat_verified",
})
MARKETS = frozenset({"BTCUSD", "XAUTUSD"})


class PortfolioReservationError(ValueError):
    pass


class FirePortfolioReservation:
    def __init__(self, root):
        root = Path(root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "fire-portfolio.sqlite"
        if self.path.is_symlink():
            raise PortfolioReservationError("Refusing symlinked portfolio lock")
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR |
                     getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        with closing(sqlite3.connect(self.path, timeout=20)) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS fire_entry_owner(
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                symbol TEXT NOT NULL, press TEXT NOT NULL,
                receipt_path TEXT NOT NULL)""")
            db.commit()

    @staticmethod
    def _receipt(path, *, press=None):
        path = Path(path)
        if not path.is_file() or path.is_symlink():
            return None
        # Only open an existing store, never create one while verifying an owner.
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro",
                                     timeout=10, uri=True)) as db:
            if press is None:
                row = db.execute(
                    "SELECT press,status FROM fire_requests "
                    "ORDER BY created_at DESC, rowid DESC LIMIT 1").fetchone()
            else:
                row = db.execute(
                    "SELECT press,status FROM fire_requests WHERE press=?",
                    (press,)).fetchone()
        # An initialized but unused second-market receipt store is safe.
        # A missing owner-specific receipt is NOT safe to release.
        return ("", "empty") if press is None and row is None else row

    @staticmethod
    def _has_other_unresolved(path, *, allowed_press=None):
        """Search all historical receipts, not just the latest visible one.

        Read-only against each per-market ledger. Missing, replaced or corrupt
        stores fail closed; the active request is the only permitted exception
        and is checked separately in claim().
        """
        path = Path(path)
        if not path.is_file() or path.is_symlink():
            return True
        terminal = tuple(sorted(TERMINAL_SAFE))
        placeholders = ",".join("?" for _ in terminal)
        sql = ("SELECT 1 FROM fire_requests WHERE status NOT IN ("
               + placeholders + ")")
        params = terminal
        if allowed_press is not None:
            sql += " AND press!=?"
            params += (allowed_press,)
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro",
                                     timeout=10, uri=True)) as db:
            db.execute("PRAGMA query_only=ON")
            return db.execute(sql + " LIMIT 1", params).fetchone() is not None

    def claim(self, symbol, press, current_store):
        if symbol not in MARKETS:
            raise PortfolioReservationError("Unrecognized FIRE market")
        try:
            press = UUID(str(press)).hex
        except (TypeError, ValueError, AttributeError):
            raise PortfolioReservationError("Invalid FIRE receipt id") from None
        current_store = Path(current_store).resolve()
        if current_store.parent != self.path.parent.resolve():
            raise PortfolioReservationError("FIRE stores must share one account directory")
        paths = {
            "BTCUSD": self.path.parent / "fire-ops.sqlite",
            "XAUTUSD": self.path.parent / "fire-xaut.sqlite",
        }
        paths[symbol] = current_store
        with closing(sqlite3.connect(self.path, timeout=20)) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT symbol,press,receipt_path FROM fire_entry_owner WHERE singleton=1"
            ).fetchone()
            if row is not None:
                old_symbol, old_press, old_path = row
                if old_symbol == symbol and old_press == press:
                    return False  # No duplicate worker/admission.
                old_state = self._receipt(old_path, press=old_press)
                if old_state is None or old_state[1] not in TERMINAL_SAFE:
                    return False
            # Also inspect legacy/outstanding FIRE from before installation.
            # Missing stores are allowed only when no previous owner exists.
            for name, store_path in paths.items():
                latest = self._receipt(store_path)
                if latest is None:
                    if store_path.exists():
                        return False
                    continue
                if latest[1] not in TERMINAL_SAFE | {"empty"} and not (
                    name == symbol and latest[0] == press
                ):
                    return False
                # A later terminal receipt can mask an older pending, exposed
                # or unknown-status FIRE. Inspect every row and only exempt
                # the exact current request, which is validated below.
                if self._has_other_unresolved(
                    store_path, allowed_press=press if name == symbol else None
                ):
                    return False
            request = self._receipt(current_store, press=press)
            if request is None or request[1] not in ("requested", "reasoning"):
                return False
            db.execute(
                "INSERT OR REPLACE INTO fire_entry_owner VALUES (1,?,?,?)",
                (symbol, press, str(current_store)))
            db.commit()
            return True
