# Dashboard redesign: the Household Snapshot as the hero

Source: the Impeccable Dashboard critique of 2026-11-25 (24/40; saved locally under `.impeccable/critique/`, not committed), followed by a brainstorm with the owner. Mockups from that brainstorm are in `.superpowers/brainstorm/` (git-ignored): `hero-b-plus-chart.html` and `palette-a-light-dark.html` are the approved ones.

## Intent

The owner opens the Dashboard to answer one question: **can we spend?** He reads the Household Snapshot for that, and he is currently its only reader. Today the snapshot shares a grid with three other panels, is surrounded by gradients, colored cards and indigo, and a positive Safety Margin shows in amber. Amber reads as a warning even when everything is fine. The page should feel **calm and reassuring**: neutral by default, with color only where action is needed.

How the owner reads the two figures:
- **Safety Margin** decides whether spending is OK.
- **Spendable** is the weekly budget target he aims for.

## Goals

1. The Household Snapshot becomes the full-width hero at the top of the Dashboard, on desktop and phone.
2. Inside it, Safety Margin is the dominant figure and Spendable is secondary.
3. A 3-month chart of the checking balance's low point each week sits in the hero.
4. A single "Needs attention" strip gathers everything that asks for action.
5. There is one calm palette (slate + deep teal), defined once as named colors with light and dark values, used by the Dashboard and the shared components. Leftover indigo elsewhere renders as teal through a temporary alias.
6. The parked minor items from the RiskBanner masking fix are folded in.

## Non-goals

- No change to any money calculation. Safety Margin, Spendable, the lowest-balance figures, cushion status and the risk walk stay exactly as `docs/architecture.md` describes them.
- No per-page redesign of the other pages (Forecast, Spending, Transactions, and so on). They only pick up the palette through the alias and the shared components.
- No new reader or role features. Shared-household views are out of scope.
- No new fonts.

## Anti-goals (a failure even if it technically works)

- **The chart disagrees with the numbers.** If the lowest bar doesn't equal "Lowest in the next 3 months", or a bar's amber doesn't match the cushion status the banner and the lowest-balance rows use, the redesign has made the app less trustworthy. The owner routinely cross-checks figures.
- **The balance-hidden setting leaks.** Any amount newly rendered in clear text while "Hide balances" is on: chart tooltips, axis labels, the attention strip, `aria-label`s.
- **Losing "How calculated" or "What changed"** next to a figure, or losing the `VerificationFlagButton` on the snapshot.
- Amber or red appearing on an ordinary, fine day.
- A visibly half-converted app, where indigo sits next to teal.

## Constraints

- **Money calcs.** Read `docs/architecture.md` before touching anything near them. The chart is display only, and it must come from the same walk as the displayed low. `_lookahead_window` / `_lookahead_minimum` in `backend/services/budget_snapshot.py` include unbilled card bills and ignore locked statement-payoff dips via `floor_mask`. The raw `/forecast` range does not necessarily match that, so **the chart's data comes from the backend**, computed alongside `lookahead_minimum`. It is not re-derived in the browser from `forecastApi.range`.
- **Amber rule.** A week's bar is amber when its low is below the cushion, and red when it is below $0. This matches `cushion_status` (`backend/services/cushion.py`), the same rule `lookahead_status` and the risk banner use. The backend returns each week's status; the frontend doesn't recompute it.
- **Masking.** Every amount goes through `useBalancesHidden()` / `maskIfHidden` / `maskMoneyText` (`frontend/src/store/balanceVisibility.ts`). With balances hidden, the chart keeps its bar shapes and dates but shows no amounts (no tooltip amount, no axis values).
- **Tooling.** Frontend uses bun only and `bun:test`. The pre-push gate runs `bun install --frozen-lockfile`, `bun audit`, and `bunx vite build`. Backend uses uv only, with the ruff `S` + `F` gate and the coverage floor in `backend/.coveragerc`.
- **Dark mode.** Tailwind `darkMode: "class"` (`frontend/src/store/theme.ts` toggles `dark` on `<html>`), already used in 67 files. Charts read `document.documentElement.classList.contains("dark")` for colors.
- **Repo.** Public repo: commits, tests and fixtures use made-up amounts. Commit directly to `main` and don't push without the owner's OK. The live backend runs `uvicorn --reload`: a backend change hits real data on save, so back up the DB before any backend commit (`backup_database()`).
- **Accessibility.** Text contrast is WCAG AA (4.5:1 body, 3:1 large). Body text is at least 13px. Tap targets are at least 44px on phone.

## Approaches considered (palette rollout)

1. **Whole app in one pass.** Named colors plus a sweep of all ~270 indigo uses across 52 files, alongside the Dashboard work. Consistent, but one very large diff that touches pages nobody critiqued. Rejected.
2. **Named colors plus Dashboard now, with a temporary indigo alias. (Chosen by the owner.)** Define the palette once, rebuild the Dashboard and the shared pieces on it, and remap Tailwind's `indigo` scale to teal so no page looks half-converted. Later page passes replace `indigo-*` classes with the named colors, and the alias is deleted at the end.
3. **Alias only.** Remap indigo to teal and stop. It's a one-line change, but the gradients and colored cards stay, and the code says "indigo" while showing teal. Rejected.

## The design, as decided

### Palette (slate + deep teal)

Named semantic colors, defined once as CSS variables in `frontend/src/index.css` (light on `:root`, dark on `.dark`) and exposed through `tailwind.config.js` `theme.extend.colors`:

| Name | Use | Light | Dark |
|---|---|---|---|
| `surface` | page background | `#f8fafc` | `#0b1220` |
| `card` | card background | `#ffffff` | `#131c2e` |
| `ink` | primary text, figures | `#0f172a` | `#e2e8f0` |
| `muted` | labels, secondary text | `#64748b` | `#94a3b8` |
| `line` | borders, dividers | `#e2e8f0` | `#22304a` |
| `bar` | ordinary chart bars | `#cbd5e1` | `#334155` |
| `accent` | links, active nav, lowest bar | `#0f766e` | `#2dd4bf` |
| `accent-strong` | primary button background (white text) | `#0f766e` | `#0f766e` |
| `warn` | amber bar/marker | `#d97706` | `#f59e0b` |
| `warn-text` | amber text | `#92400e` (figure `#b45309`) | `#fcd34d` (figure `#fbbf24`) |
| `warn-bg` / `warn-line` | attention strip | `#fef3c7` / `#fde68a` | `#2a1a06` / `#5a3a0e` |

Red for below $0 keeps the existing `expense` color family. The existing `income` / `expense` / `warning` / `projected` names stay for the pages that use them.

The **temporary alias** remaps Tailwind's `indigo` scale to a teal scale in `tailwind.config.js`, with a comment that it is temporary and lists the follow-up.

**Shared components** move onto the named colors: `.card`, `.btn-primary`, `.btn-secondary`, `.btn-ghost`, `.input`, the body and html surfaces in `index.css`, and the nav in `Layout.tsx` / `MoreSheet.tsx`.

### Hero (desktop)

The layout follows mockup B, plus the chart from mockup C.

```
┌ Household Snapshot ───────────────────────────── [flag] ┐
│ SAFETY MARGIN · this week        │ SPENDABLE · target    │
│ $1,240   (large, ink)            │ $430 left  (medium)   │
│ $177/day · $4,900 this month     │ $61/day · on pace     │
│ [Pull $X from savings → when savings_pull_needed > 0]    │
│ CHECKING LOW POINT EACH WEEK · next 3 months             │
│ ▂▅▃▆▄▇▃█▅▆▄▅▃   (13 bars, lowest in accent, amber/red)   │
│ Dec        Jan        Feb                                │
│ Lowest next month: $… · Dec 12 · Lowest in 3 months: …   │
│ How calculated · What changed                            │
└──────────────────────────────────────────────────────────┘
```

- The hero spans full width at the top of the Dashboard, above every other panel. It replaces the snapshot's slot in today's 2/4-column grid.
- **Safety Margin column.** It's wider, about 1.4fr against 1fr. The figure is about 40px desktop and 36px phone. It's `ink` at $0 or above and red below $0. That's the same condition under which the backend sets `savings_pull_needed > 0`, so red always arrives with the "Pull $X from savings" action. The figure itself has no amber state. The owner decided this because Safety Margin already measures the low point against $0, and the cushion warning lives on the chart bars. Today's "positive shows amber" is removed.
- **Spendable column.** About 22px. Its on-pace/over-pace line stays. Green and red tints go; "over pace" uses `warn-text`.
- **Existing behavior that stays:**
  - the "this month" lines
  - `HowCalculated` and `WhatChanged` beside each figure
  - `WhatChanged` (leftover) and `VerificationFlagButton` on the card
  - the "Pull X from savings" line, now styled as the action
  - the lowest-balance rows (from `lowestBalanceRows`), as the chart caption, with their existing "move money into checking" lines
- No gradient background.

### Chart

- **Bars.** One bar per week for the 13 weeks starting this week, each bar the lowest checking balance that week. It uses the same walk and window as `lookahead_minimum`, so the lowest bar equals "Lowest in the next 3 months".
- **Colors.** The lowest bar is `accent`. Weeks below the cushion are `warn`, and weeks below $0 are red.
- **Interaction.** Hovering or tapping a bar shows its week, amount and date, masked when balances are hidden. Month labels sit under the bars.
- **Size.** Small: about 40–52px tall. It's a glance, not the Forecast page.

### Phone

The same hero stacked: Safety Margin, then Spendable, then chart, then caption. `SafetyMarginHero` and `SpendableTile` are replaced by, or rebuilt as, this shared hero, so phone and desktop show the same thing. The "+ Plan a one-off" button stays below the hero.

### "Needs attention" strip

- **Placement.** Directly under the hero, on desktop and phone.
- **Contents.** It gathers what currently renders as separate blocks under the header: `RiskBanner`, `PlannedTransferReminder`, `BillsToConfirm`, `AmountDrift`.
- **Calm state.** When none of them has anything to show, the strip collapses to one quiet line: "Nothing needs you today." (`muted` text on `card`).
- **Active state.** It uses `warn-bg` / `warn-line`. The individual items keep their own behavior and actions.

### Rest of the page

- Available to Spend, Net Position, Month in Review, Balance Flow, the weekly digest, Checking / Credit Cards, and Upcoming Bills keep their content, below the strip, as neutral `card`s on the named colors.
- Gradients and decorative tints are removed.
- Chart line colors that are hard-coded indigo (for example `#6366f1` / `#a5b4fc` in the phone balance chart) move to `accent`.
- Text is at least 13px, contrast is AA, and phone tap targets are at least 44px.

### Masking follow-ups (from the RiskBanner fix)

- A typed transfer Amount clears when balances become hidden.
- The "Show balances to edit the amount" hint becomes visible text, not only a `title` tooltip.
- RiskBanner uses the shared mask helper or constant, not a hard-coded `••••••`.
- The `riskBannerText` LEAKS list covers more than two-decimal formats.
- The hidden Amount span gets a test.

## Calls made after the builder check (the DA's, not the owner's; correct any)

- **Walk.** The chart reads `display_window`, the walk behind `lookahead_minimum` and the next-month low. It does not read Safety Margin's `lookahead_window`. The bars answer "how low does checking get", the same question the caption rows answer.
- **Weeks.** These are rolling 7-day buckets starting today, matching the app's rolling "this week" (`_weekly_allowance` prorates by days, not calendar weeks). The bars cover the whole display window and are never cut short. A shorter last bucket is fine, so the true 3-month low is always inside the bars. Days masked by `floor_mask` are excluded from a bucket's low, the same way they are excluded from `display_min`. A bucket with every day masked renders as an empty gap.
- **Lowest-bar color.** Status wins. A bucket below $0 is red and one below the cushion is amber, including the lowest one. `accent` marks the lowest bar only when its status is OK. Ties go to the earliest bucket, which matches the earliest-date tie rule for the displayed low.
- **Scenarios.** `weekly_lows` takes the same `proposal` / `overrides` arguments as the other lows, so it follows an active scenario.
- **Attention strip.** The four existing components are wrapped, not rewritten. The builder adds a shared "has content" signal (for example, each exposes a hook or reports up) so the strip knows when to show "Nothing needs you today." The strip container is neutral, with a "Needs attention" label. Each item keeps its own styling, moved onto the named colors (`warn-*` for warnings). A RiskBanner that is only informational is not forced into amber.
- **Old phone components.** `SafetyMarginHero` and `SpendableTile` are imported only by `Dashboard.tsx`, so they are deleted once the shared hero replaces them.
- **Alias scope.** Remapping the `indigo` scale covers every `indigo-*` utility (text, bg, border, ring, hover, focus). Hard-coded indigo hex values are replaced on the Dashboard and in shared components only. Those on other pages (for example, the charts in `Spending.tsx`, `Forecast.tsx`, `NetWorth.tsx`) go on the follow-up list next to the alias comment.
- **Live data.** This change adds a read-only snapshot field and no migration:
  - Back up with `backup_database()` before any backend commit, because the dev server reloads on save.
  - Verify with Interceptor on the dev frontend first.
  - Deploy to `:8443` with `scripts/deploy.sh` only after the owner says deploy, then re-verify there.
  - Any migration stays held until the owner approves it.

## Left to the builder

- The backend shape of the weekly-lows data. One option is a `weekly_lows` list on the budget snapshot (`start`, `end`, `amount`, `date`, `status`), computed inside `compute_budget_snapshot` from `display_window`. Whatever the shape, add a test asserting its minimum equals `lookahead_minimum` and that each `status` comes from `cushion_status`.
- The component breakdown: hero, chart, strip, and where `lowestBalanceRows` lives.
- Whether the chart uses the existing chart library (recharts, already used for Balance Flow) or plain divs/SVG.
- The exact teal scale used by the indigo alias. It must keep AA contrast wherever indigo text sits on white or on the dark card.
- Task order and test plan. The plan should verify in real Chrome via the Interceptor skill, on the live app at `https://df-macbookpro16.local:8443`, in light and dark, desktop and phone width, with balances shown and hidden.

## Addendum 2026-11-26: wide-window polish (approved mockups `chart-before-after.html`, `wide-right-column.html`)

Seen on the owner's wide window (~2050px): the chart's lowest bar renders as a hairline, the bars become slabs, Spendable drifts far right, and the selected-week caption sits between the bars and the month labels.

**Chart (`WeeklyLowsChart`)**
- Bars scale from **$0**, not from the lowest to the highest week. Height is `amount / max(maxAmount, cushion)` of the chart height (about 64px).
- A week below $0 renders as a 4px red stub at the baseline.
- A **dashed cushion line** is drawn at `safety_cushion`, in `muted`. It is text-free, so nothing leaks while hidden.
- Bars are about 40px max width with 6px gaps, left-aligned, never stretched.
- Order: bars, then month labels aligned to bar positions, then the selected-week caption, then the "Lowest …" rows.
- The status and accent rules are unchanged.

**Hero (`SnapshotHero`)**
- The content is capped at about 960px.
- The Spendable column sits next to Safety Margin (`auto auto` columns with a gap), not at the far edge.

**Very wide windows (main content about 1450px or more; the builder picks the breakpoint)**
- The hero (about 960px) and a right column sit side by side.
- The right column holds the **Needs attention** strip, then the existing **Upcoming Bills** card, moved rather than duplicated.
- Below that width, the layout stays as it is now: the hero, then the strip stacked full width, and Upcoming Bills in its current place.
- The DA's call: the right column reuses the existing Upcoming Bills card unchanged (next 30 days, top 8), not a new 7-day list. That avoids two bill lists, and the soonest bills are listed first anyway.

**Unchanged:** money logic, masking, statuses, phone layout. The moneyGuard allowlist entry for the bar-height line is re-keyed to the new display-only expression.
