# "How is this calculated?" — Design

the user wants every heavily calculated number to explain itself: an info icon on
the box that opens the actual math with his real numbers and a one-line
reason per step. Today the Dashboard has a static **?** on two boxes that
describes the formula in general terms, never with the numbers behind the
value on screen.

Approach chosen (over rebuilding the math in the frontend, which duplicates
every formula and is the exact bug class this app has hit before, and over
automatic operation tracing, which is heavy and unlabelled): **each
calculation reports its own steps**, built from the same variables it just
used, and a test replays those steps to the cent.

## Scope

In:
- Dashboard (`budget_snapshot.compute_budget_snapshot`): Left to Spend,
  Spendable this week, Spendable today, Safety Margin (month), Safety Margin
  (week), and the 3-month lowest point.
- Budget page (`left_to_budget.compute_left_to_budget`): unassigned.
- Recurring page (`month_summary.build_month_summary`): expense_total and
  left_over.
- One shared frontend component that renders any explanation.

Out:
- Spending averages and the Balance Flow headline. The component makes them
  cheap to add later.
- Any change to how any number is computed.

## 1. The shape

In `backend/schemas.py`:

```
ExplainRow:
  op: "start" | "add" | "subtract" | "divide" | "result"
  label: str
  amount: Decimal          # for "divide", the divisor (e.g. 3.43 weeks)
  note: str | None         # one-line "why"
  children: list[ExplainChild] = []

ExplainChild:
  label: str
  amount: Decimal
  note: str | None

Explanation:
  title: str
  result: Decimal
  rows: list[ExplainRow]
```

Replay rule (used by the tests and trusted by the UI): start from the
`start` row's amount, apply each `add` / `subtract` / `divide` row in order,
and quantize to cents after a divide. The value must equal `result` and the
metric's displayed value exactly. A `result` row closes the list and repeats
`result`. When a row has children, their amounts sum to the row's amount
(signs as displayed).

A single helper, `backend/services/explain.py`, holds an `ExplainBuilder`
(`start`, `add`, `subtract`, `divide`, `build`) plus `replay(explanation)`,
so every calculator builds explanations the same way and the tests share
one replay.

## 2. Per-metric content

The wording is a starting point; the implementer may tighten it but must keep
the steps.

- **Left to Spend** = `leftover` (start; children: income, recurring bills
  this month, committed savings, groceries budget, the same parts
  `leftover_parts` returns) − new card spend (children: per active card,
  `current − statement + pending`) + card bills already charged this month
  ("recurring subscriptions already posted to a card this month").
- **Spendable this week** = Left to Spend ÷ weeks left in the month
  (`days_remaining / 7`). When 7 or fewer days remain, it's a single `start`
  row noting "last week of the month: the whole amount". This mirrors
  `_weekly_allowance` exactly.
- **Spendable today** = Spendable this week ÷ days left this week.
- **Safety Margin** = 3-month lowest checking balance (start; note gives the
  date and "excludes the already-scheduled card payoff") − this month's card
  bills (the full "Credit Card Bills" list) + card bills already charged.
- **Safety Margin (week)** = Safety Margin ÷ weeks left, same rule as above.
- **3-month lowest point**: a single `start` row with the date and a note;
  there is no arithmetic to replay.
- **Budget, unassigned** = leftover (children as above) − each assigned
  bucket (one `subtract` row per assignable category with a non-zero amount).
- **Recurring, expense_total** = monthly bills subtotal (children: each
  monthly-frequency occurrence) + each bill hitting this month (one `add`
  row each).
- **Recurring, left_over** = income (children: each occurrence) − expense
  total − each one-off out + each one-off in.

Response fields: `BudgetSnapshot.explain: dict[str, Explanation]` (keys
`left_to_spend`, `spendable_week`, `spendable_today`, `safety_margin`,
`safety_margin_week`, `lookahead_minimum`), `LeftToBudgetOut.explain_unassigned:
Explanation`, and `MonthSummaryOut.explain: dict[str, Explanation]` (keys
`expense_total`, `left_over`). All are additive. Existing fields are unchanged.

## 3. Frontend

- `frontend/src/components/HowCalculated.tsx`: a small ⓘ button
  (`aria-label="How is {title} calculated?"`) that opens a Radix Dialog (the
  same package `ConfirmDialog` uses; no new dependency). The dialog shows
  `title`, then a receipt-style ledger: the operator symbol, label, amount
  right-aligned in tabular numbers, and the gray note under each row. Rows
  with children expand on click. It ends with a bold "= result" row.
  Optional `helpText` renders behind a "What does this mean?" disclosure.
- Amounts go through the existing hidden-balances masking (`maskIfHidden` /
  `useBalancesHidden`) so hiding balances hides them here too.
- Mounting:
  - Dashboard: next to each covered box label, replacing the current **?**
    buttons. Their static text moves into `helpText`.
  - Budget: next to "Left to budget".
  - Recurring summary strip: next to the Expenses and Left over headlines.

## Testing

- Backend:
  - For each explanation, `replay()` equals the metric's value, and `result`
    equals the value.
  - Children sum to their parent row.
  - Use the existing spreadsheet-verified fixture in
    `tests/test_budget_snapshot.py` for the Dashboard metrics, plus the
    Left-to-budget and month-summary fixtures.
  - The last-week-of-month single-row case is covered.
  - A guard confirms every pre-existing numeric field is unchanged.
- Frontend: type-check gate (no new errors).
- Interceptor: each icon opens, and each receipt's total equals its box.
