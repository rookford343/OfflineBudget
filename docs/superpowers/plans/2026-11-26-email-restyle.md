# Daily Email Restyle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Restyle the daily summary email to match the redesigned Dashboard. This follows the owner-approved mockup `.superpowers/brainstorm/*/content/email-before-after.html` (2026-11-26).
- Slate and teal neutral cards.
- Safety Margin leads as the big figure (ink, or red below $0, with the pull-from-savings action under it).
- Spendable comes second.
- The weekly low-point bars are drawn with email-safe tables.
- A "Needs attention" block, with "Nothing needs you today." when quiet.
- A subject line that gives the answer and never includes amounts.

**Architecture:** This changes presentation only, in `backend/services/summary_generator.py` (`generate_daily_summary` HTML assembly, ~lines 460-640) and the subject in `backend/main.py:227`.
- Every figure, line and "since last email" note the email sends today stays.
- Only the styling, the order and the subject change.
- The plain-text body keeps its content. It is only re-ordered to match.

**Tech Stack:** Python, FastAPI, pytest via uv.

**Spec:** the owner-approved mockup above, plus the Dashboard spec `docs/superpowers/specs/2026-11-25-dashboard-redesign-design.md`. That spec covers the Safety Margin tone rule (ink or red, never amber), the chart tone rules, and the palette hex values.

## Global Constraints

**Content and money**
- No money calculation changes. Read only the fields already on `BudgetSnapshot`, including `weekly_lows`, `safety_cushion` and `savings_pull_needed`.
- Every piece of information the email shows today still appears:
  - the since-last-email lines;
  - the stale-bank-data warning;
  - the last-pull line;
  - the lowest-balance rows;
  - the move-to-checking line;
  - the pending-cards note;
  - the checking, upcoming, cards, weekly digest, month and "what changed" sections.
- Only the order and the styling change.

**Palette (light, inline hex)**

| Name | Hex |
|---|---|
| page background | `#f8fafc` |
| card | `#ffffff` |
| card border | `#e2e8f0` |
| ink | `#0f172a` |
| muted | `#64748b` |
| accent | `#0f766e` |
| bar | `#cbd5e1` |
| warn-bg | `#fef3c7` |
| warn-line | `#fde68a` |
| warn-text | `#92400e` |
| warn bar | `#d97706` |
| red | `#dc2626` |

**Dark mode**
- A `@media (prefers-color-scheme: dark)` block in `<head>` overrides via classes, using the Dashboard dark values: page `#0b1220`, card `#131c2e`, border `#22304a`, ink `#e2e8f0`, muted `#94a3b8`, accent `#2dd4bf`, bar `#334155`, warn-bg `#2a1a06`, warn-text `#fcd34d`.
- Inline styles stay the light defaults, so a client that strips `<style>` still renders correctly.

**Tones**
- The Safety Margin figure is ink at $0 or above and red below $0.
- Bars:
  - `danger` is red;
  - `warning` is the warn bar;
  - the lowest bar with status `ok` is accent;
  - otherwise bar;
  - a null amount renders as an empty cell.
- Bar heights are `amount / max(maxPositive, cushion) × 48px`. A week at or below $0 is a 3px stub.
- The lowest bar is the earliest minimum.

**Subject line (amount-free)**
- When `savings_pull_needed > 0`, use `Action needed: pull from savings · Daily Budget Summary — {Month D, YYYY}`.
- Otherwise, when the lookahead status is `danger` or `warning` or the move-to-checking line applies, use `Heads up: low point ahead · Daily Budget Summary — …`.
- Otherwise use `Covered this week · Daily Budget Summary — …`.
- Keep the existing ` + Weekly Digest` suffix rule.
- Never include an amount or digits other than the date.

**Order**
1. header and last-pull line;
2. hero (Safety Margin, then Spendable, then bars, then lowest rows and move-to-checking);
3. Needs attention (stale bank data, move-to-checking, pull-from-savings, or "Nothing needs you today.");
4. what changed;
5. checking;
6. upcoming;
7. credit cards;
8. weekly digest;
9. month.

**Layout**
- Max width 600px, mobile-first.
- `word-break` and overflow protections kept as today.
- No emoji in section headings: plain 14px semibold titles, matching the mockup.

**Repo rules**
- uv only. Never touch `.db` files. Never send a real email from tests.
- Commit to `main` and do not push.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Made-up amounts in tests.

## Review Focus

1. **No information lost.** For a full fixture snapshot, every label and figure the old HTML contained still appears in the new HTML: the since-lines, the move-to-checking line, the pending note and the stale warning. Pinned in Task 2.
2. **Subject never leaks amounts.** For each of the three states, the subject contains no `$` and no digits except the date. Pinned in Task 1.
3. **No `weekly_lows`, or all gaps.** The hero renders without bars and does not raise. Pinned in Task 2.
4. **Safety Margin exactly 0.** The figure renders in ink (`#0f172a`), not red and not amber. Pinned in Task 2.
5. **Dark-mode block present.** A dark-mode media query exists in the HTML, and inline light defaults remain on the hero card. Pinned in Task 2.

---

### Task 1: Amount-free answer subject line

**Files:**
- `backend/services/summary_generator.py`: add `email_subject(snap, today: date, with_weekly: bool) -> str`.
- `backend/main.py:227-229`: use it.
- `backend/tests/test_email_subject.py`: new.

- [ ] **Step 1: Write the failing tests** for the three states, each with `with_weekly` true and false.
  - Exact strings, for example `Covered this week · Daily Budget Summary — November 26, 2026`.
  - The `+ Weekly Digest` suffix appears only when `with_weekly` is true.
  - For each state, `re.sub(r"[A-Z][a-z]+ \d{1,2}, \d{4}", "", s)` leaves no digit and no `$`.
- [ ] **Step 2: Run and confirm failure.**
- [ ] **Step 3: Implement**, using the snapshot fields named in Global Constraints.
- [ ] **Step 4: Verify.** Run `uv run --locked pytest backend/tests/test_email_subject.py backend/tests/test_email_scheduling.py -q && uv run --locked ruff check . && uv run --locked python -c "import backend.main, cli.budget"`. Expected: all pass.
- [ ] **Step 5: Commit** with the message `feat: daily email subject leads with the answer, amount-free`.

### Task 2: HTML restyle, hero with weekly-lows bars, Needs attention block

**Files:**
- `backend/services/summary_generator.py`: the HTML assembly in `generate_daily_summary`, `_section`, the household block, the `<head>` style block, and the text-body order. Add a pure helper `_weekly_lows_bars_html(lows, cushion) -> str` with the geometry from Global Constraints.
- New test file: `backend/tests/test_email_restyle.py`.
- Existing email tests: update only assertions that pin old styling (colors, emoji headings, the old order). Never weaken a content assertion. List each change with the reason in the report.

- [ ] **Step 1: Write the failing tests** in `backend/tests/test_email_restyle.py`. Build snapshots the way the existing tests do; see `test_summary_generator_next_month_low.py` for a blank-snapshot pattern.
  - `test_hero_leads_with_safety_margin`: in the HTML, "Safety Margin" comes before "Spendable this week", and both come before "Checking".
  - `test_margin_tone`: at 0.00 the figure style has `#0f172a`. At -0.01 it has `#dc2626`. Amber `#d97706` never appears on the figure.
  - `test_bars_geometry`: lows of 2500, 800 and 1000 with cushion 1000 give heights 48px, 15px and 19px. Statuses are respected. The lowest `ok` bar uses `#0f766e`. A null amount gives an empty cell.
  - `test_no_weekly_lows_renders`: with an empty `weekly_lows`, there is no bars table and no exception.
  - `test_needs_attention_quiet_and_active`: with nothing to flag, "Nothing needs you today." appears. With `savings_pull_needed > 0`, a "Needs attention" heading plus the pull line appear, and the quiet line does not.
  - `test_no_information_lost`: for a full fixture, all of these appear: every since-line string passed in, the move-to-checking line, the pending note text, the last-pull line, and the section titles Checking, Upcoming, Credit Cards, Weekly Digest and the month title.
  - `test_dark_mode_block`: the HTML contains `prefers-color-scheme: dark`, and the hero card carries both an inline `background:#ffffff` and its dark class.
- [ ] **Step 2: Run and confirm failure.**
- [ ] **Step 3: Implement** to match the mockup.
- [ ] **Step 4: Verify.**
  - Run `uv run --locked pytest backend/tests -q -k "email or summary"`, then the full `uv run --locked pytest backend/tests -q`, ruff, and the import check.
  - Render one sample HTML file to `/tmp/ob-email-sample.html` using a test fixture with made-up data, not the real database, and give its path in the report.
- [ ] **Step 5: Prove the guard can fail.** Temporarily make the margin figure amber when positive, confirm `test_margin_tone` fails, then restore.
- [ ] **Step 6: Commit** with the message `feat: restyle daily email to match the calm Dashboard`.
