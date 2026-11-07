"""Version of the money-calculation rules.

Hand-bumped integer. Bump it in any commit that changes what a calculation
means (not refactors that keep every figure identical), and add a matching
`- vN:` line to the "Calculation changelog" in docs/architecture.md.
"""

CALC_VERSION: int = 12

# Copied from the "Calculation changelog" in docs/architecture.md (a test keeps
# them equal); change history quotes it when a figure moved because the rules did.
CALC_CHANGELOG: dict[int, str] = {
    1: "baseline after 2026-11-06 fixes.",
    2: "one real-spending rule; refunds net everywhere; savings budget lines show money moved to savings",
    3: "one pending freshness rule",
    4: "one walk policy; weekend overrides",
    5: "card-payment model shared by forecast and snapshot; scenario card bills in Safety Margin",
    6: "one cushion for safety, risk and wish list",
    7: "budget export reads the Budget page's actuals",
    8: "subscription-fallback cards no longer double-count in Safety Margin; refunds match by lookback, not query window",
    9: "risk banner skips locked statement-payment dips, like the 3-month low",
    10: "net worth has one recipe; assets include account balances",
    11: "Available to Spend rebuilt before budgets on the shared layer",
    12: "Available to Spend counts balance-only cards like Left to Spend",
}
