# AI response reliability
Increase completion allowance to 8192 tokens (reasoning models may spend tokens
before final JSON) and provider socket timeout to 90 seconds. Require a concise
JSON-only response, accept one complete fenced JSON object, reject truncated
responses even if their text resembles valid JSON. Persist redacted response
diagnostics for failures: error category, timing, sizes, finish reason and token
usage if available. No raw completions or credentials in diagnostic logs.
No automatic paid retry, no signal-claim reset, no trading strategy or broker
policy changes. Higher token allowance can increase API cost; timeout is a
socket timeout rather than a total request deadline. Live success must be
verified on subsequent naturally occurring signals.