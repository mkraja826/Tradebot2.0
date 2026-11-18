# GPT-6 FIRE — explicit Delta India DEMO BTCUSD execution

**Implementation complete in GitHub; exchange-connected live commissioning
is NOT yet verified. Production (real money) is unsupported.** No exchange order
has been placed by the build/test process. This is an operator-enabled
testnet-only workflow, not automatically activated by code deployment.

## Roles

- **GPT-6 (`tb-gpt-6`)** alone chooses LONG or SHORT, contract count, SL, TP.
- FIRE is a single browser press, with no Kimi veto or second model call.
- **DeepSeek V4.1 Flash** continues its independent read-only 24/7 scanner.
- **Kimi K3.1 Pro** is an independent trade research/learning watcher when
  its separate service is enabled. Kimi cannot create or modify trades.
- The exchange adapter only checks validity, rejects duplicate requests,
  submits the GPT-6 decision and verifies broker results. It does not choose
  a strategy.

## Execution contract

1. User presses **FIRE · EXECUTE DEMO** on the existing Cloudflare
   Access-protected private browser dashboard. One same-origin POST
   `/api/fire` is created; the server chooses the request UUID.
2. Server records a durable request, collects one fresh signed Delta Demo
   BTCUSD snapshot and asks **GPT-6 only** for direction, size, SL and TP.
3. Fresh signed BTC quote, mark price, existing orders and BTC positions are
   checked again immediately before entry. During first supervised pilot,
   the maximum is **one BTCUSD Demo contract** per FIRE.
4. Server commits a durable order intent before exactly one signed
   `POST /v2/orders`, attaching
   `bracket_stop_loss_price` and `bracket_take_profit_price`, with
   `bracket_stop_trigger_method=mark_price`.
5. The parent order is independently queried by its client ID. A complete
   fill must be confirmed. The active broker order book must have two
   distinct opposite-side **bracket stop-loss** and **bracket take-profit**
   orders with matching stop prices and a matching signed open position.
6. If accepted but not filled, if an error occurs after an uncertain POST,
   or if the SL/TP protections cannot be verified, the engine attempts
   BTC-only reduce-only emergency closeout and fresh flatness verification.
   Unresolved results remain **exposure_unknown**, prohibit new FIRE requests
   and require manual review. No timeout automatically reposts a new order.
7. Independent systemd `tradebot2-fire-watchdog` checks the position, parent
   fill and SL/TP every 15 seconds. It runs even if the browser/dashboard
   stops and attempts a BTC-only closeout if known FIRE protection disappears.
   Broker outages can still prevent this; systemd/VM failure is not proof
   of protection.
8. Once a position and all orders are confirmed absent, FIRE becomes
   `flat_verified`. Repeated presses and accidental retries do not create
   duplicate entries. A five-minute paid-request cooldown applies.

The verification uses the documented Delta India bracket-order behavior:
https://docs.delta.exchange/ and
https://guides.delta.exchange/delta-exchange-india-user-guide/trading-guide/order-types

**Do not use the same Demo account for manual trading or another execution bot**
while this pilot is active: the emergency closeout is deliberately BTC-only
but can affect *other BTC orders* in that account.

## VM deployment: prepare read-only, verify, then opt in

Run as the usual VM SSH user (not root). Never show private keys in screenshots.

    cd ~/Tradebot2.0
    git pull --ff-only
    source .venv/bin/activate
    python -m pip install -e .
    python -m unittest discover -s tests -p 'test_fire*.py'

Run a signed **read-only** flatness verification before activating orders:

    source ~/.config/tradebot2/keys.env
    python -m tradebot.pilot_verify

You should see `verified_flat: true`, zero BTC positions and zero pending
orders. Otherwise stop and reconcile with Delta Demo first.

Install the independent watchdog **before** enabling FIRE execution:

    bash ops/install_fire_watchdog_service.sh
    sudo systemctl is-active tradebot2-fire-watchdog

Expected status: `active`. The watcher does not start trades itself and
does not invoke paid models. Leave the existing Cloudflare Access app and
Tunnel enabled; NEVER open public VM firewall port 8765.

To explicitly activate Demo FIRE on the already working private dashboard:

    TRADEBOT_CONFIRM_FIRE_DEMO=YES-DELTA-DEMO bash ops/enable_fire_demo.sh
    curl -s http://127.0.0.1:8765/api/fire

The JSON should have `execution_enabled: true` and mode
`delta_india_demo_execution`. It does **not** place any order by itself.
The browser displays `FIRE · EXECUTE DEMO` after refreshing. The first
actual testnet POST occurs only when you press that button.

Follow its phases: `reasoning` → `preflight` → `submitting` →
`reconciling` or `verifying_protection` → `protected_active`,
`flat_verified`, or `exposure_unknown`. Inspect real Delta Demo exchange
orders, not just the browser status.

To stop **new** trades:

    bash ops/disable_fire_demo.sh

The watchdog remains running to monitor any existing position. Disabling
new FIRE does **not** close a currently open position. To inspect non-secret
watchdog health:

    sudo systemctl is-active tradebot2-fire-watchdog
    sudo journalctl -u tradebot2-fire-watchdog -n 30 --no-pager

Never stop the watchdog while an existing FIRE position is open. A missing
stop or target requires immediate exchange inspection; no software system
can guarantee a closeout during broker outages.

## Current limits and next gate

The pilot cap is 1 BTCUSD Demo contract per press. This is an order-execution
safety limit, not a Kimi/DeepSeek strategy filter. Before increasing it,
verify a *real exchange-connected* entry/fill/SL/TP/exit cycle including
rounding to contract tick sizes, fees/funding and recovery from timeouts.
If the broker normalizes an off-tick target, the controller conservatively
treats unmatched child stop prices as **unverified** and attempts a closeout.

The Kimi watcher and trade-memory system remain separate. Candidate Kimi
lessons are not automatically injected into GPT-6. Verified actual P&L,
fees and trade attribution are still a later milestone.
