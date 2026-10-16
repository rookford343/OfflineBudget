# Bonus forecasting — design

Status: approved in chat 2026-10-16. Figures below are illustrative; real
salary and bonus values live only in the user's database.

## Problem

The forecast has no idea bonuses exist. A user paid one or more annual
bonuses sees checking drift below zero in the months before payout, and the
multi-year view keeps sliding because every year's bonus is missing. Bonuses
also count toward the Social Security wage base, so leaving them out pushes
the forecast's "SS withholding stops" date too late in the year.

## Model

A user has a **base salary** and an **expected yearly raise**:

- `users.annual_salary` (gross; the existing Tax-profile field, reused) for
  `users.annual_salary_year`
- `users.annual_raise_pct` (e.g. 3.5)
- Salary for year Y = `annual_salary × (1 + raise)^(Y − annual_salary_year)`

A **bonus plan** describes one bonus the user is paid every year:

| Field | Meaning |
|---|---|
| `recurring_item_id` | The yearly income item that carries the deposit (name, account, payout month/day, matching). One plan per item. |
| `target_pct` | e.g. 20 |
| `salary_lag_years` | Which salary the % applies to: 1 = last year's, 3 = three years back (a grant that vests over three years). |
| `withholding_pct` | Gross → net, e.g. 30 (supplemental federal + FICA + state/county). Defaulted from a real past bonus when one exists. |

`bonus_plan_years` holds fixed gross amounts for specific years
(`plan_id, year, gross_amount`), for ramp years the employer states
outright. A fixed amount always wins over the formula.

Gross for year Y = fixed amount for Y if present, else
`target_pct × salary(Y − salary_lag_years)`. Net = gross × (1 − withholding).

Example (illustrative): salary 100,000 in 2026, raise 3%. Plan A (20%, lag 1)
pays 20,000 gross in 2027. Plan B (20%, lag 3) with fixed 2027 = 12,000 and
2028 = 17,000 pays those, then 20,000 in 2029 (20% of 2026 salary).

## Forecast engine

- The backing item is a normal yearly income item, so firing, the Friday
  shift for weekend dates, and "a linked actual this month suppresses the
  projection" all apply unchanged.
- When a bonus item fires, its amount is the plan's **net for that year**,
  not `item.amount`. `item.amount` is kept equal to the next payout's net so
  every other screen (Recurring page, budget totals) shows a sensible figure.
- **Social Security:** a projected bonus reduces `ss_remaining_gross` by its
  gross. If that crosses the wage base, the bonus itself gets the partial
  boost (`excess × 6.2%`), exactly like a crossing paycheck; later paychecks
  get the full boost. A bonus actually received after the SS checkpoint date
  in the checkpoint's year is drawn down by its gross in the same
  reconciliation that already handles received paychecks. (Only with a pay-stub
  checkpoint: the legacy `ss_bonus_ytd` mode already has the user's bonus
  figure, so counting deposits there would double it.)
- Bonus items are never tagged as paychecks for the SS boost, whatever their
  net-to-gross ratio.
- Before the year's payout, the forecast shows the bonus as an ordinary
  projected income line named after the item.

## UI

Settings → Tax gains a **Salary & bonuses** section:

- Base salary, the year it applies to, expected yearly raise.
- A list of bonus plans: pick an existing yearly income item (created on the
  Recurring page with frequency Yearly), target %,
  salary lag (last year / 3 years back), withholding %, and a small table of
  fixed amounts by year.
- Each plan shows its computed gross/net for the next three payouts so the
  user can check the numbers against what HR gave them.

## Matching

No change. The real deposit lands on the payout date with the payroll
descriptor; the matcher links it by date, the ±15% amount rule against the
item's amount, and payee history. Two plans paid the same day have different
amounts, so each deposit links to its own plan.

## Out of scope

- Paycheck raises (paychecks stay at their recurring amount; a later change).
- Any change to how 2026's already-received bonus deposits are linked.

## Testing

- Formula: lag 1 and lag 3, fixed amounts overriding, raise compounding.
- Engine: bonus appears on its date at net; weekend payout moves to Friday;
  linked actual suppresses it; next year uses next year's amount.
- SS: a bonus pulls the crossing paycheck earlier; a bonus that itself crosses
  gets the partial boost; January resets.
- API: plan CRUD is user-scoped (another user's plan is 404), fixed-year
  amounts validate (positive, sane year).
