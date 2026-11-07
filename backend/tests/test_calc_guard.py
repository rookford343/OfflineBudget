"""Guard against new duplicate money math.

An AST scan of backend/routers/*.py and backend/services/*.py with two checks:

1. No `sum(...)` or `+=` / `-=` over an attribute named `amount`,
   `pending_charges`, `balance_due` or `current_balance` outside the shared
   layer. A figure computed in a router or a screen-specific service is a
   second recipe that will drift from the first.
2. In routers only: no bare `a + b` / `a - b` where one side is a money
   attribute (the four above, or any `*_amount`, `*_balance`, `budgeted`,
   `actual`, `variance`) and the other is not a literal. That is how a
   router's one-line variance or delta used to hide from check 1.
3. No read of `.pending_charges` outside `pending.py` (the freshness rule) and
   the code that writes it. Everyone else asks `card_pending`.

When one of these fails, route the figure through the shared layer (see the
provenance table in docs/architecture.md). Allowlist it only when the code is
presentational (grouping or formatting figures the shared layer already
produced) or writes a stored value, and say why on the entry.

The scan covers bare `sum(...)` and SQL `func.sum(...)` / `sa.func.sum(...)`.
Known evasions it cannot see: accumulating through a temp variable
(`x = row.amount; total += x`), `functools.reduce`, `getattr(row, "amount")`,
and `Decimal` arithmetic spread across statements. Review catches those.
"""
import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
SCANNED = ("routers", "services")

MONEY_ATTRS = {"amount", "pending_charges", "balance_due", "current_balance"}

# Adding a module here needs a line in docs/architecture.md.
# Modules where the money math lives (or is stored), keyed by path under backend/.
SHARED_LAYER = {
    "services/month_base.py": "the month model",
    "services/real_spend.py": "the real-spending rule",
    "services/card_spending.py": "card spending this month per card, with the balance-only fallback",
    "services/pending.py": "the pending and freshness rule",
    "services/account_balances.py": "pending-adjusted account balances and the month's change on them",
    "services/net_worth.py": "net worth: assets, liabilities and the one recipe behind the live view and snapshots",
    "services/net_position.py": "Net Position and each card's cycle figures",
    "services/available_to_spend.py": "Available to Spend, before budgets, and its walk to Left to Spend",
    "services/forecast_walk.py": "the standard forecast walk",
    "services/forecast_engine.py": "the day-by-day forecast",
    "services/card_payment_model.py": "the card-payment model",
    "services/cushion.py": "the one cushion",
    "services/budget_track.py": "Track Budgets: each line's available amount and the page headline",
    "services/spending_figures.py": "Spending page: a parent's direct spend and a category's monthly average",
    "services/recurring_math.py": "a recurring item's monthly equivalent and an override's variance",
    "services/forecast_baseline.py": "the saved start-of-month forecast and Balance Flow's headline figures",
    "services/savings_series.py": "combined savings balance per day for the Forecast chart",
    "services/metric_history.py": "change history: collects every headline figure and receipt, sums a pending list for the checking-balance receipt",
    "services/calc_version.py": "the calculation version",
    "services/tax_service.py": "tax estimates, their own domain",
    "services/bank_sync_service.py": "writes synced balances and pending charges",
    "services/plaid_sync_service.py": "writes synced balances and pending charges",
    "services/import_service.py": "writes imported balances",
    "services/planned_auto_settle.py": "settles a one-off against a real charge",
    "services/statement_reconcile.py": "reconciliation domain: matches a statement's credits to synced card rows, not a headline figure",
}

# The few other places that touch these attributes, one function at a time, each with a reason.
# An entry that no longer matches a violation fails the test, so this list only shrinks.
PRESENTATIONAL_OR_WRITER = {
    # Writers: they keep a stored balance in step with a user action.
    "routers/credit_cards.py:record_payment": "writes the checking and card balances when a payment is recorded",
    "routers/transactions.py:create_transaction": "writes the account balance for a manual transaction",
    "routers/transactions.py:delete_transaction": "writes the account balance back when a transaction is deleted",
    # Presentational: groups figures the shared layer already produced, no second rule.
    "routers/spending.py:spending_monthly": "buckets real_spend verdicts by month",
    "routers/spending.py:spending_yearly_trends": "buckets real_spend verdicts by month",
    "routers/spending.py:spending_rolling_monthly": "buckets real_spend verdicts by month",
    "routers/spending.py:tax_summary": "total line of the tax export",
    "routers/spending.py:tax_estimate": "tax domain: sums the year's deductible transactions as an input to estimate_taxes",
    "routers/forecast.py:get_monthly_summary": "opening balance read off a forecast day (custom range)",
    "services/explain.py:children_consistent": "checks an explanation's own arithmetic",
    "services/explain.py:replay": "replays an explanation's own rows",
    "services/budget_snapshot.py:leftover_parts": "composes the month model's primitives",
    "services/budget_snapshot.py:compute_budget_snapshot": "composes the shared primitives into Left to Spend",
    "services/spendable_pacer.py:_recurring_card_charges_in_range": "sums month-model card bills",
    "services/spendable_pacer.py:discretionary_spend_card": "sums real_spend verdicts the pacer keeps",
    "services/spendable_pacer.py:discretionary_spend_checking": "sums real_spend verdicts the pacer keeps",
    "services/budget_plan.py:_items_by_category": "folds month-model occurrences into plan items",
    "services/budget_plan.py:compute_budget_plan": "totals month-model occurrences for the plan page",
    "services/reconciliation_helper.py:compute_reconciliation": "totals matched card autopays to compare with the estimate",
    "routers/credit_cards.py:add_card_transaction": "writes the card balance for a manual card charge",
    "routers/transactions.py:update_transaction": "writes the account balance back when a transaction's amount is edited",
    "routers/spending.py:spending_monthly_by_category": "buckets real_spend verdicts by month and category",
    "routers/spending.py:spending_by_category": "buckets real_spend verdicts by category and source",
    "routers/spending.py:spending_by_card": "buckets real_spend verdicts by category",
    "routers/spending.py:spending_sankey": "buckets real_spend verdicts by category",
    # No shared primitive yet.
    "routers/goals.py:_enrich": "goal remaining = target minus current, two stored fields; no shared recipe yet",
}

# Check 2 only: reads of `.pending_charges` that are not the model column or that stamp it.
PENDING_READ_ALLOWED = {
    "routers/credit_cards.py:_stamp_pending_charges_freshness": "stamps when the hand-typed field changed",
    "routers/credit_cards.py:update_card": "remembers the previous value to stamp the change",
    "services/summary_generator.py:generate_daily_summary": "reads the snapshot card's already-fresh pending_charges",
}
PENDING_READ_MODULES = {
    "services/pending.py", "services/bank_sync_service.py", "services/plaid_sync_service.py",
}


def _has_money_attr(node: ast.AST) -> bool:
    return any(isinstance(n, ast.Attribute) and n.attr in MONEY_ATTRS for n in ast.walk(node))


def _is_sum(func: ast.expr) -> bool:
    """`sum`, `func.sum` or `sa.func.sum` (a SQL aggregate)."""
    if isinstance(func, ast.Name):
        return func.id == "sum"
    return (isinstance(func, ast.Attribute) and func.attr == "sum"
            and (isinstance(func.value, ast.Name) and func.value.id == "func"
                 or isinstance(func.value, ast.Attribute) and func.value.attr == "func"))


def _is_money_name(attr: str) -> bool:
    return (attr in MONEY_ATTRS or attr.endswith(("_amount", "_balance"))
            or attr in {"budgeted", "actual", "variance"})


def _has_money_name(node: ast.AST) -> bool:
    return any(isinstance(n, ast.Attribute) and _is_money_name(n.attr) for n in ast.walk(node))


def _is_literal(node: ast.AST) -> bool:
    return isinstance(node, (ast.Constant, ast.JoinedStr))


def find_violations(source: str, binops: bool = False) -> list[tuple[str, int, str]]:
    """(top-level function or class, line, check) for each violation in `source`.
    `binops` also flags bare money `+`/`-` (the routers-only check)."""
    found = []
    for top in ast.parse(source).body:
        name = getattr(top, "name", "<module>")
        for node in ast.walk(top):
            if (isinstance(node, ast.Call) and _is_sum(node.func)
                    and any(_has_money_attr(a) for a in node.args)):
                found.append((name, node.lineno, "sum"))
            elif (isinstance(node, ast.AugAssign) and isinstance(node.op, (ast.Add, ast.Sub))
                    and _has_money_attr(node.value)):
                found.append((name, node.lineno, "augmented"))
            elif (binops and isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub))
                    and not _is_literal(node.left) and not _is_literal(node.right)
                    and (_has_money_name(node.left) or _has_money_name(node.right))):
                found.append((name, node.lineno, "binop"))
            elif (isinstance(node, ast.Attribute) and node.attr == "pending_charges"
                    and isinstance(node.ctx, ast.Load)):
                found.append((name, node.lineno, "pending_read"))
    return found


def _scan() -> list[tuple[str, str, int, str]]:
    out = []
    for folder in SCANNED:
        for path in sorted((BACKEND / folder).rglob("*.py")):
            rel = path.relative_to(BACKEND).as_posix()
            for func, line, check in find_violations(path.read_text(), binops=folder == "routers"):
                out.append((rel, func, line, check))
    return out


def test_no_duplicate_money_math_outside_the_shared_layer():
    offenders = []
    for rel, func, line, check in _scan():
        if check == "pending_read":
            continue
        if rel in SHARED_LAYER or f"{rel}:{func}" in PRESENTATIONAL_OR_WRITER:
            continue
        offenders.append(f"{rel}:{line} in {func} ({check} over a money attribute)")
    assert not offenders, (
        "Money math outside the shared layer; route it through backend/services "
        "(docs/architecture.md) or allowlist it with a reason:\n" + "\n".join(offenders)
    )


def test_pending_charges_is_read_only_by_the_pending_rule_and_its_writers():
    offenders = []
    for rel, func, line, check in _scan():
        if check != "pending_read":
            continue
        if rel in PENDING_READ_MODULES or f"{rel}:{func}" in PENDING_READ_ALLOWED:
            continue
        offenders.append(f"{rel}:{line} in {func}")
    assert not offenders, (
        "Read of .pending_charges outside services/pending.py; call card_pending(card, today):\n"
        + "\n".join(offenders)
    )


def test_allowlist_has_no_stale_entries():
    seen = {f"{rel}:{func}" for rel, func, _, check in _scan() if check != "pending_read"}
    seen_pending = {f"{rel}:{func}" for rel, func, _, check in _scan() if check == "pending_read"}
    stale = sorted(set(PRESENTATIONAL_OR_WRITER) - seen) + sorted(set(PENDING_READ_ALLOWED) - seen_pending)
    assert not stale, f"Allowlist entries that no longer match a violation (delete them): {stale}"
    missing = [m for m in SHARED_LAYER if not (BACKEND / m).is_file()]
    assert not missing, f"Allowlisted modules that do not exist: {missing}"


@pytest.mark.parametrize("source, check", [
    ("def f(rows):\n    return sum(r.amount for r in rows)\n", "sum"),
    ("def f(rows):\n    total = 0\n    for r in rows:\n        total += r.amount\n    return total\n", "augmented"),
    ("def f(a, b):\n    a.current_balance -= b.balance_due\n", "augmented"),
    ("def f(card):\n    return card.pending_charges\n", "pending_read"),
    ("def f(o, p):\n    return o.actual_amount - p.amount\n", "binop"),
    ("def f(q, v):\n    return v - q.close_balance\n", "binop"),
    ("def f(db):\n    return db.query(func.sum(Transaction.amount)).scalar()\n", "sum"),
    ("def f(db):\n    return db.query(sa.func.sum(-Card.current_balance)).scalar()\n", "sum"),
    ("def f(db):\n    return db.query(func.coalesce(func.sum(T.amount), 0)).scalar()\n", "sum"),
])
def test_the_scan_catches_what_it_claims_to(source, check):
    assert [c for _, _, c in find_violations(source, binops=True)] == [check]


def test_binops_are_flagged_only_when_asked_and_not_for_literals_or_text():
    source = "def f(o, p):\n    return o.actual_amount - p.amount\n"
    assert find_violations(source) == []
    clean = (
        "def f(o, n):\n"
        "    a = o.amount + 1\n"
        "    b = f'{o.amount} - {n}'\n"
        "    c = n + n\n"
        "    return a\n"
    )
    assert find_violations(clean, binops=True) == []


def test_the_scan_ignores_unrelated_sums_and_pending_writes():
    source = (
        "def f(rows, card):\n"
        "    card.pending_charges = 0\n"
        "    return sum(r.quantity for r in rows)\n"
    )
    assert find_violations(source) == []
