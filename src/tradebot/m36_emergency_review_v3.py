"""Offline emergency review projection. No broker, transport or release capability."""
from tradebot.m27_recovery_audit_v3 import project as recovery


def assess(symbol, account, monitor, unresolved, *, now, manual_halt, watchdog_healthy):
    """Classify evidence for review; no result can permit entry, retry or closeout."""
    alerts = []
    if manual_halt is not False:
        alerts.append('manual_halt_or_unknown')
    if watchdog_healthy is not True:
        alerts.append('watchdog_unverified')
    try:
        if symbol not in ('BTCUSD', 'XAUTUSD'):
            raise ValueError('market')
        r = recovery(symbol, account, monitor, unresolved, now=now)
        alerts.extend(r['alerts'])
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, OSError):
        r = {'monitor_status': 'unavailable', 'direct_flatness_observed': False}
        alerts.append('invalid_recovery_evidence')
    state = r['monitor_status']
    if state == 'open_protection_unverified':
        disposition = 'urgent_protection_review'
    elif state == 'open_protection_reported':
        disposition = 'preserve_protection_and_reconcile'
    elif state == 'flat_orders_present':
        disposition = 'reconcile_pending_orders'
    elif alerts:
        disposition = 'halt_and_reconcile'
    else:
        disposition = 'flat_diagnostic_only'
    return dict(mode='offline_emergency_review', symbol=symbol,
                disposition=disposition, alerts=alerts,
                direct_flatness_observed=r['direct_flatness_observed'],
                execution_authorized=False, retry_authorized=False,
                emergency_transport_commissioned=False,
                restart_recovery_commissioned=False,
                kill_switch_commissioned=False, orders_submitted=0)
