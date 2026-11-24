# Trading Bot 2.0 — Strategy V2 migration

**Status:** Strategy V2 public-data scanner, AI event routing contract, restart-safe
signal journal, and 60-second shadow monitor are implemented. **Live order
entry remains on the existing workers.** This plan does not authorize an order.

## Objectives

- Monitor both BTCUSD and XAUTUSD using ten independent indicator combinations.
- A qualifying moderate or strong signal from **one** detector suffices to
  request AI evaluation. Other detectors need not agree.
- GPT-6 evaluates BTC and DeepSeek evaluates Gold; model output is only a
  proposal, never broker authorization.
- Broker/demo-environment verification, risk governor, margin verification,
  stop-loss, take-profit, liquidation buffer and position reconciliation retain
  final authority over order admission.
- Preserve five-minute post-close cooldown and prevent duplicate active orders
  on a single isolated subaccount.
- Self-heal data/provider/process interruptions without clearing unknown or
  potentially exposed broker states.

## Components and boundaries

| Layer | Code | Side effects |
|---|---|---|
| Candle verification and indicator detectors | `multi_strategy_signals.py` | None |
| Validated 1-of-10 AI-routing contract | `signal_ai_router.py` | None |
| Strategy V2 orchestration | `strategy_v2/pipeline.py` | Public candle GET only |
| Persistent shadow signal ledger | `strategy_v2/journal.py` | Private SQLite observations only |
| Earlier smoke monitor | `signal_shadow_scan.py` | Public candle GET only |
| BTC execution | `btc_autonomous_demo.py` and FIRE modules | Existing controlled demo order path |
| Gold execution | `gold_autonomous_demo.py` and FIRE modules | Existing controlled demo order path |

The two live execution workers currently **do not consume** the Strategy V2
journal, and the new shadow pipeline never calls an AI or places an order.

The shadow timer runs `tradebot.strategy_v2.pipeline` once each minute using
public Delta India demo market history. It is isolated from BTC/Gold account
keys and all order APIs. The journal is stored at
`data/strategy-v2/signal-observations.sqlite`, mode 0600, inside a
user-owned 0700 folder. It is not an account, margin or execution ledger.

## Migration stages

1. **Baseline/reconciliation.** Inventory live uncommitted VM changes against
   GitHub `main` and avoid destructive resets; keep the old execution workers
   functional throughout migration.
2. **Detectors and read-only observation (implemented).** Ten detectors, closed
   5m candle validation, one qualifying signal, duplicate/contradiction
   representation, persistent candle-level event IDs. Run live shadow scans.
3. **Research and calibration.** Score definitions, signal frequency, false
   positives, fees/spread/slippage and walk-forward tests on BTC and Gold
   independently. Current 60/80 thresholds are uncalibrated heuristics.
4. **AI input contract.** Extend existing GPT-6 BTC / DeepSeek Gold decision
   adapters to receive versioned signal evidence and full checked market
   context, while preserving broker execution validation.
5. **Durable dispatch state.** Add transactional event reservation, outcome
   attribution and post-restart reconciliation. Merely observing a signal
   must never cause a duplicate AI request or order.
6. **Gated demo deployment.** Gradually enable signal-driven AI requests on
   the isolated demo accounts with isolated rollback switches and complete
   SL/TP verification; disable unconditional model polling only after tests.
7. **Recovery.** Classify verified no-order model/preflight/data/provider
   failures separately from uncertain execution, reconcile existing BTC halt
   via the approved evidence-based process, and keep hard stops for missing
   protection or unknown broker exposure.
8. **Observability/quality gates.** Dashboard per strategy: signals, trigger
   reasons, AI accept/reject, submitted orders, broker fills, net P&L, drawdown,
   fees, protection state, signal-to-order latency and recovery evidence.

## Acceptance criteria

- Every detector can emit LONG and SHORT candidates from completed candles.
- One qualifying detector is enough to generate a routeable AI event.
- Multiple detections on the same candle yield one durable candidate.
- Opposite directions are labeled conflicting, not auto-executed.
- Restarts and repeated scans never create duplicate candidate records.
- Missing/stale/nonconsecutive candles, unverified volume or malformed
  broker data never authorize an order.
- No changes to BTC/Gold isolated account credentials, original FIRE receipts
  or the main/mixed account.
- Existing stop-loss/take-profit, active-position and five-minute cooldown
  checks remain in control.
- Both broker+AI integration tests and full demo lifecycle tests pass before
  enabling a signal-driven trading worker.

## Active blockers at architecture inception (2026-11-24)

- BTC autonomous order entry is **halted**, despite a running worker. The
  latest receipt documents a no-order `exchange_preflight_failed` attempt but
  does not meet the existing audited release procedure.
- Do not delete the BTC halt flag, fake evidence, bypass root-shell safety
  restrictions or treat a process restart as execution authorization.
- Numerous unrelated live VM changes are not reconciled with GitHub `main`;
  do not perform a destructive checkout or rewrite existing FIRE modules.
- Gold's execution service remains working on its existing protected path and
  must not be disrupted by a shadow-only upgrade.

## Reproducible checks

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p test_multi_strategy_signals.py -q
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p test_signal_ai_router.py -q
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p test_strategy_v2_pipeline.py -q
PYTHONPATH=src .venv/bin/python -m tradebot.strategy_v2.pipeline
systemctl status tradebot2-signal-shadow.timer
```

## Rollback

Remove only the `tradebot2-signal-shadow.service.d/20-strategy-v2.conf`
override and reload systemd to restore the original public-data shadow
scanner. Do not modify BTC/Gold worker units, trade ledgers or halt markers.
