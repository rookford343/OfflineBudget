# Balance Flow vs. Forecast — Design

The Dashboard's Balance Flow card compares this month's actual checking
balance (solid line) against last month's (dashed line). the user wants it to show
**how far the month is deviating from the forecast** instead, with the card
looking exactly as it does now.

"The forecast" means the forecast **as it stood at the start of the month**
(chosen over a live recomputation, which would move every time a recurring
item is edited and so hide real deviation). The app does not keep past
forecasts today, so the start-of-month forecast has to be saved.

## Scope

In:
1. Save each account's day-by-day forecast for the month once, at the first
   opportunity in that month, and never overwrite it.
2. An endpoint that returns a month's saved forecast.
3. The Balance Flow card uses it as its comparison line when one exists.

Out:
- Backfilling months with no saved forecast (it cannot be done honestly:
  inputs have changed since). September 2026 keeps the current
  last-month comparison; the new view starts 2026-10-01.
- Any change to the forecast engine, Left to Spend, Safety Margin or other
  Dashboard cards.

## 1. Data

Reuse `MonthlyForecastSnapshot` (`backend/models.py`), which already has one
row per `(user_id, account_id, year, month)` via a unique constraint and is
currently never written. Add two nullable columns (ALTERs in
`database.upgrade_schema()`):

- `taken_on: date` — the day the forecast was saved.
- `daily_points: text` — JSON list of `{"date": "YYYY-MM-DD", "projected_balance": "1074.64"}`,
  one per day from the 1st to the last day of the month.

`forecasted_open` / `forecasted_close` are set from the first and last point.

## 2. Saving: `ensure_month_baseline`

New `backend/services/forecast_baseline.py`:

- `ensure_month_baseline(db, user_id, account_id, as_of: date) -> MonthlyForecastSnapshot`
  — if a row exists for `as_of`'s year/month, return it unchanged. Otherwise
  run `build_forecast(db, user_id, account_id, first_of_month, last_of_month)`,
  store the points, `taken_on = as_of`, and return the new row.
- Never updates an existing row. Idempotent.
- **Save window:** a new row is only created when `as_of.day <= 7`
  (`BASELINE_SAVE_WINDOW_DAYS = 7`). Later in the month it returns `None`
  and the month has no baseline. A forecast saved late is mostly actuals and
  would report near-zero deviation, which misleads; the window still covers a
  Mac that slept through the 1st. This is also what keeps September 2026 on
  the fallback view.
- If saved after the 1st but inside the window, days up to `taken_on` are
  actuals in the saved points, so deviation for those days is zero by
  construction; the card notes the save date.

Triggers (both call the same function):
- `main._scheduler_sweep` (every 20 minutes): for every active checking
  account, `ensure_month_baseline(..., date.today())`. Failures are logged
  and never break the sweep's existing jobs.
- The endpoint below, for the current month only.

## 3. Endpoint

`GET /forecast/baseline?account_id=&year=&month=` →
`{ year, month, taken_on, points: [{date, projected_balance}] }`

- Account must belong to the user, otherwise 404.
- Current month: calls `ensure_month_baseline` (creates on first request
  inside the save window); `None` → 404.
- Past or future month with no row: 404. Past month with a row: returns it.
- Declared before any path-parameter route in `routers/forecast.py`.

## 4. The card (same look)

`frontend/src/pages/Dashboard.tsx`, Balance Flow card:

- New query `["forecast-baseline", accountId, year, month]`. If it 404s or has
  no points, the card renders exactly as today (actual vs. last month).
- With a baseline:
  - Solid area line: actual balance month-to-date (unchanged).
  - Dashed line: saved forecast for every day of the month (replaces last
    month's line; same color, dash and width).
  - Headline: `actual_today − forecast_today`, green when ≥ 0, red when < 0,
    masked like today when balances are hidden.
  - Subtitle: "{Month} so far, vs. forecast from {Mon D}" (`taken_on`).
  - Footer: "Forecast for day {N}: {forecast_today} ({pct}%)", where pct is
    the deviation relative to the forecast value.
  - Tooltip series names: "{Month}" and "Forecast".
- Same chart size, gradient, grid, axes and animation.

## Error handling

- Engine failure while saving: log, return 503 from the endpoint (the card
  falls back to today's view), sweep continues.
- Malformed `daily_points` JSON: treated as no baseline (fallback view).

## Testing

Backend (pytest):
- `ensure_month_baseline` saves one row with one point per day of the month
  and `taken_on`; a second call returns the same row unchanged even after a
  recurring item changes; day 7 creates, day 8 returns `None` and creates nothing.
- Endpoint: current month creates; past month without a row 404s; another
  user's account 404s.
- Sweep helper creates baselines for active checking accounts only and
  swallows a failing account.

Frontend: type-check gate (no new tsc errors). Interceptor now: the card
still renders the fallback view in September and the baseline endpoint 404s.
Interceptor on or after 2026-10-01: dashed forecast line, headline, subtitle
and footer render. The live database is never seeded with a fake baseline.
