# Demo execution increment

- Only Delta India testnet is used. Fixed order leverage 20x must be confirmed by the exchange.
- AI receives wallets by asset, available balance, product specification and current product positions.
- AI chooses side, integer contract size, intended margin allocation in settlement units and SL/TP.
- Entry uses a market order with the AI entry reference logged; actual fill may differ. Native bracket trigger prices are attached to entry using mark price.
- The capital allocation is an AI budget recorded in the journal; actual margin depends on exchange contract size, fill price, fees and account configuration. This increment does not independently reconcile the intended budget with actual margin or total portfolio equity across currencies.
- Stable order IDs and durable reservation prevent duplicate submission; ambiguous orders are reconciled, not replayed.
- No loss, equity, confidence or fixed sizing gates were added. Directional price validation and leverage confirmation are request correctness checks.
- The existing public scanner/decision CLI remains non-executing. The new evaluate_and_execute function is an explicit integration entrypoint, not an unattended service.
- No authenticated request, deployment or actual demo trade was performed. Verify exchange bracket behavior and position lifecycle in testnet before unattended use.
