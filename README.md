# Tradebot 2.0

A Bitcoin-only autonomous research and **Delta Exchange India demo/testnet** execution project.

## Agreed requirements

- **Exchange**: India demo/testnet only. No production endpoint or live account support in this repository.
- **Markets**: BTC derivatives only: futures and options.
- **Strategy autonomy**: An AI planner may propose futures and options strategies, including multi-leg strategies. The AI determines whether to trade or remain flat.
- **Session**: Monday–Friday, 09:30–16:00 **America/New_York**. No new entries after 15:45. All positions should be flattened before the end of the session.
- **Learning**: Journal decisions, market observations, and results; evaluate model revisions offline before deploying them.
- **Controls**: Technical safeguards, idempotent client-order IDs, stale-data checks, and an emergency stop. Strategy decisions remain autonomous.

## Project status

**Foundation under development. Not deployed.** No API keys are configured. There is no running AI agent or verified end-to-end trading yet. The signed API client and session logic are being added and tested incrementally. Never infer that positions are flat merely because a close request was submitted; verify them through the exchange.

## Environment

Delta India demo REST API: `https://cdn-ind.testnet.deltaex.org`. Delta's production API host is deliberately disallowed.

Never commit credentials. Use demo-only API credentials in environment variables after making sure the static egress IP is whitelisted on Delta.

Official API docs: https://docs.delta.exchange/
