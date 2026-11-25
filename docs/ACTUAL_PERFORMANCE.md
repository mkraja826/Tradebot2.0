# Actual demo performance
Read only recorded exchange fills. Require a known flat anchor, continuous
position sizes, a linear contract with equal quote/settlement asset, and
matching gross realized P&L and cumulative commission at flat close.
Exclude reversals, ambiguous timestamps, missing fields and unverified
history. Cashflow sum over flat-to-flat fills handles partial closes.
Report net before funding explicitly; funding may be absent, and is not
assumed zero. Match a single opening order to its acknowledged receipt
and deterministic Recover decision ID; otherwise do not credit Recover.
Historical account trades are distinct from Recover trades. Rule
co-occurrence is not a causal attribution and cannot be summed across
rules. Dashboard API reports the verified subset, not account-wide P&L.
No execution actions or AI calls.
