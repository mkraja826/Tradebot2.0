# Delta India DEMO — GitHub 401 classification without private log data

Previous signed broker preflight run
[45022363296](https://github.com/mkraja826/Tradebot2.0/actions/runs/45022363296)
returned HTTP **401** for authenticated GET
`/v2/users/trading_preferences`. The GitHub Actions secret variables were
nonempty but that does **not** verify they are active, correct or permitted
from a GitHub-hosted runner.

Official reference: https://docs.delta.exchange/#authentication

## Diagnostic

One single authenticated GET to the existing India DEMO host, signed with
the existing key/secret; no request mutation, retries, order endpoints or
account transfers. It checks only the **exact** provider error code and
allows these fixed outcomes, with unknown responses fully redacted:

| Diagnostic category | Possible explanation |
|---|---|
| INVALID_OR_WRONG_ENV_KEY | revoked/incorrect key or production key used on DEMO |
| KEY_PERMISSION_DENIED | key lacks account endpoint rights |
| SOURCE_IP_NOT_WHITELISTED | GitHub runner IP isn't on that key's allowlist |
| SIGNATURE_EXPIRED | clock/timestamp window failed |
| SIGNATURE_MISMATCH | HMAC signing data or secret mismatch |
| UNKNOWN_OR_REDACTED | no recognized safe category; no diagnosis inferred |

In all failure cases the result remains blocked, without leaking any
`message` field, URL, response text, IP address, user ID, key fragment,
signature, wallet amount or account identifier. Do not add ephemeral GitHub
runner IPs to the **trading key** allowlist merely to make a check pass.
Prefer the already-approved static outbound IP and original protected VM.

## Operator resolution

1. Confirm the key exists on the **Delta India DEMO** account rather than
   the production site; do not paste either secret in chat or GitHub logs.
2. Verify key's permissions and IP allowlist through the DEMO account's API
   Management interface. A 401 diagnostic may identify only a category, not
   prove credential validity.
3. If the key is VM-IP-bound (recommended), **do not weaken its whitelist**.
   Run the existing read-only release audit on the pre-approved VM with
   consistent logs, and do not run a second trade.
4. Only after authenticated API access succeeds, establish current leverage,
   real isolated-margin account mode and two independent account-wide
   exposure/order snapshots. Then resolve M09 wallet evidence, suspicious
   historical candles, equity opening receipts, watchdog and off-host alert
   commissioning and an independent release review.

The diagnostic's `TRADING_ENABLED` flag is always false. A passing auth
GET does not establish full broker risk readiness or permission to FIRE.
