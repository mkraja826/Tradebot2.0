"""Deprecated import location for the shared equity policy core.

All equity calculations and runtime validation now live in equity_policy_core.
Keep this alias until downstream deployments and import checks are migrated.
No legacy admission bypass or alternate risk implementation is provided.
"""
import sys
from tradebot import equity_policy_core

sys.modules[__name__] = equity_policy_core
