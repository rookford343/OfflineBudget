# Forecast Risk Callout + Weekly Spending Digest — Design

## Problem

Two gaps identified against the current app (last real commit 2026-05-13):

1. The Forecast page has a passive red zero-line on the balance chart, but no active signal telling Dan when the checking account is projected to go negative. He has to eyeball the chart.
2. Spending has Month/3Mo/YTD/LastYr views but no weekly cadence, and no delivery mechanism. Dan and his wife (who won't log into the app) need a recurring, low-friction way to see category spending and top merchants so they can course-correct before the weekend.

## Goals

- Forecast page shows an explicit callout when the account is projected to dip below the account's low-balance threshold within the forecast horizon — not just the existing passive chart line.
- A weekly digest (category totals + top merchants + the risk callout) is generated every Friday morning, emailed to a configurable recipient list, and also viewable in-app as a fallback.

## Out of Scope

- Tech debt (Alembic migrations, full pytest suite, Vite bundle splitting, React error boundaries) — evaluated and confirmed non-blocking for this build; see Decisions.
- Full user account + login for Dan's wife — she receives the digest by email only, not as an app user.
- Push notifications, SMS, or any delivery channel beyond email + in-app.
- Monthly digest delivery — monthly spending is already viewable in-app via the existing Month/YTD filters; only the weekly cadence is new.

## Prerequisite (not part of this build, but blocking for email delivery)

SMTP is not configured in `.env` (`SMTP_HOST` etc. are unset). The weekly digest's in-app panel will work regardless; the email half is a no-op until SMTP is configured. Flagging so it isn't a surprise when the first Friday digest doesn't arrive by email.

## Design

### Feature A — Negative-balance risk callout

**Backend** (`backend/services/forecast_engine.py`, `backend/routers/forecast.py`):
- After computing the existing day-by-day balance array, scan forward from today for the first day where `balance < threshold` (threshold = the account's `low_balance_threshold` if set, else 0 — same default the existing red reference line uses).
- Add `risk: { at_risk: bool, date: str | null, amount: number | null, threshold: number }` to the forecast response.

**Frontend** (`frontend/src/pages/Forecast.tsx`):
- New `RiskBanner` component, rendered above the chart only when `at_risk` is true: "Projected to go below $X on <date>." No banner when `at_risk` is false.

This calculation is computed once, server-side, so both the Forecast page and the weekly digest (Feature B) consume the same value — no duplicated risk logic.

### Feature B — Weekly digest (Friday email + in-app fallback)

**New settings** (`backend/config.py`, additive via existing `upgrade_schema()` pattern — no Alembic needed):
- `digest_recipients: list[str]` — plain email addresses, stored independently of `User` accounts.
- `WEEKLY_DIGEST_DAY` (default `"fri"`), `WEEKLY_DIGEST_HOUR` (default matches the existing `DAILY_SUMMARY_HOUR` pattern, morning).

**Backend**:
- `backend/services/summary_generator.py`: new `generate_weekly_digest(db)` — trailing 7 days of transactions, grouped by category (reuse the existing category-spending query from `routers/spending.py`), top-N merchants (reuse the existing merchant-ranking query), plus the Feature A risk callout.
- `backend/main.py`: new `_send_weekly_digest()` scheduled as a sibling to the existing `_send_daily_summaries` APScheduler job — `_scheduler.add_job(_send_weekly_digest, "cron", day_of_week=settings.WEEKLY_DIGEST_DAY, hour=settings.WEEKLY_DIGEST_HOUR)`.
- New endpoint `GET /spending/weekly-digest` — returns the same payload as JSON. Powers the in-app panel and lets the digest content be tested without waiting for Friday.

**Frontend**:
- New panel (Dashboard) rendering the digest JSON: category breakdown (reuse existing Spending.tsx chart/table patterns) + top merchants table + risk callout. Acts as the fallback while SMTP is unconfigured, and as a permanent secondary surface afterward.

## Data Flow

Both features read from existing `Transaction` / `Category` / `Account` tables. No new core spending data model. Only new persisted state is the digest recipients list and the two new settings — additive, handled by the existing `upgrade_schema()` idempotent `ALTER TABLE` pattern.

## Error Handling

- SMTP failures already no-op silently and log via the existing `email_service.py` — the weekly job reuses that path, so a misconfigured or down SMTP server never crashes the scheduler.
- A week with zero transactions still sends/renders a "$0 spent" digest rather than being skipped — avoids a silent gap in the record.
- Risk calculation defaults threshold to 0 when `low_balance_threshold` is unset, matching the existing chart's default.

## Testing

No pytest suite exists yet in this project (confirmed tech debt). Rather than building one up front, this build adds narrow, scoped coverage for only its two new pure-logic pieces:
- Risk-date detection (given a balance array and threshold, returns the correct first-breach date or `at_risk: false`).
- Weekly category/merchant aggregation (given a transaction set, returns correct totals and rankings).

Frontend changes verified manually via Interceptor (real Chrome) per LifeOS convention — no new frontend test framework introduced.

## Decisions

- 2026-08-03: Confirmed tech debt (Alembic, full pytest suite, bundle splitting, error boundaries) is non-blocking for this build. The one genuinely blocking issue — a broken `.venv` left over from a project directory move (`~/Programming/OfflineBudget` → `~/Programming/Dev/OfflineBudget`) that prevented the backend from starting at all — was found and fixed during the fundamentals check, separate from this design.
- 2026-08-03: Digest recipients are plain email addresses, not full `User` accounts, since Dan's wife will not log into the app.
- 2026-08-03: Risk calculation lives server-side in `forecast_engine.py` specifically so Feature B can reuse it rather than reimplementing balance-crossing logic in the digest generator.

## Next Step

Design approved by Dan (2026-08-03) but not yet turned into an implementation plan — that's the first action for the next session: invoke the `writing-plans` skill against this spec to produce the step-by-step implementation plan, then execute. Nothing has been implemented yet beyond the fundamentals fix (venv rebuild) already committed separately.
