"""Existing-only child ledger selection for the V3 policy migration.

This adapter supplies the existing equity evaluator with an explicitly scoped
ledger. It does not establish broker identity, arm an executor, replace loss
thresholds, or grant order authority. Callers still need independently verified
broker/account binding and the existing execution and protection checks.
"""
from pathlib import Path
from stat import S_ISREG

from tradebot.equity_policy_core import EquityRiskError, RuntimeEquityGuard

_CHILD_DIRS = {"BTCUSD": "btc-isolated", "XAUTUSD": "gold-isolated"}
_LEDGER = "fire-equity-risk.sqlite"


def scoped_equity_ledger(data_root, symbol):
    """Resolve only a pre-existing, private child ledger; never use parent."""
    if type(symbol) is not str or symbol not in _CHILD_DIRS:
        raise EquityRiskError("unsupported_isolated_demo_market")
    root = Path(data_root)
    child = root / _CHILD_DIRS[symbol]
    ledger = child / _LEDGER
    try:
        if (root.is_symlink() or not root.is_dir()
                or child.is_symlink() or not child.is_dir()
                or ledger.is_symlink()):
            raise ValueError("invalid child path")
        st = ledger.stat()
        if (not S_ISREG(st.st_mode) or st.st_nlink != 1
                or ledger.resolve().parent != child.resolve()):
            raise ValueError("invalid child ledger")
    except (OSError, ValueError, RuntimeError):
        raise EquityRiskError("isolated_equity_ledger_unverified") from None
    return ledger


def child_equity_guard(data_root, symbol):
    """Construct the existing-only evaluator, retaining its risk limits."""
    return RuntimeEquityGuard(scoped_equity_ledger(data_root, symbol))
