---
task: "Securo-Inspired Frontend Uplift — Phase 1"
slug: 20260820-offlinebudget-securo-frontend-uplift-phase1
project: OfflineBudget
effort: E4
effort_source: classifier
phase: scoping
progress: 1/29
mode: interactive
started: 2026-08-20T00:00:00Z
updated: 2026-08-24T00:00:00Z
---

## Problem

OfflineBudget's UI works but reads as functional rather than polished next to
comparable self-hosted budgeting apps. A competitive scan of Securo
(usesecuro.com/github.com/securo-finance/securo, AGPL-3.0, full research and
screenshot-derived notes at `docs/securo-comparison.md`) surfaced concrete,
reimplementable UI patterns OfflineBudget doesn't currently have: pages that
fit one viewport height with no scroll, a plain-language pacing sentence on
the dashboard instead of a chart the user has to interpret, a consistent
icon-left dropdown/progress-bar treatment, and a grouped rather than flat
settings menu. Dan wants the frontend uplifted to match before any Phase 2
feature work (household splitting, investment tracking, etc. — tracked
separately, out of scope here).

## Vision

Opening OfflineBudget feels as tight as the best self-hosted finance apps in
its category: the Dashboard fits one screen with no scrolling, a plain-English
sentence tells you at a glance whether you're on pace or heading for trouble
this month, budget category rows read at a glance via consistent progress
bars, and every page — light or dark — feels like one coherent design system
rather than a page-by-page patchwork. Nothing about the code or assets is
borrowed; every pattern here is rebuilt in OfflineBudget's own components from
written observation of a competitor's UI.

## Out of Scope

Phase 2 feature work — household expense splitting, investment/asset
portfolio tracking, credit-card billing-cycle auto-grouping, 2FA — is
explicitly out of scope for this ISA; see `docs/securo-comparison.md` §
"Phase 2 — Feature work" for that separate future pass. No backend schema
changes. No new API endpoints beyond what's needed to surface data the
backend already computes (e.g. the pacing sentence uses existing forecast
output). No Securo AI-agent-style feature. No Kubernetes/Helm deploy tooling.
No multi-currency support. Copying Securo's Cash Flow report is explicitly
rejected as redundant with OfflineBudget's existing Forecast page (Decisions).

## Constraints

- **License boundary (hard constraint):** Securo is AGPL-3.0. No source file,
  CSS, SVG/icon asset, or image from `github.com/securo-finance/securo` may be
  copied, adapted-in-place, or vendored into this repo. Every claim below is
  implemented as an independent OfflineBudget component built from written
  pattern descriptions in `docs/securo-comparison.md`, never by referencing
  Securo's actual source.
- All visual changes must work in both dark and light mode (existing project
  convention, carried forward from the prior Tier 3 ISA).
- Zero new TypeScript errors (`npx tsc --noEmit` must pass after changes).
- Do not modify backend Python files for any claim in this ISA — this is a
  frontend-only pass. The one exception is if the pacing-sentence claim (F8)
  needs a new computed field; if so, it must reuse the existing forecast
  calculation, not introduce new financial logic (that belongs to a separate,
  reviewed change).
- Existing "progressive disclosure" philosophy (one headline number, detail
  one click away) is a design identity to reconcile against, not discard —
  Securo's denser stat-header pattern must be adapted down, not copied
  wholesale (see F3).

## Goal

Ship the nine Phase 1 frontend patterns identified in
`docs/securo-comparison.md` — chart vocabulary audit, category progress bars,
a reconciled dashboard stat header, dark/light parity, spacing/density pass,
nav flattening, fit-to-viewport no-scroll layout, and a plain-language pacing
sentence — verified via grep/build checks and confirmed license-clean via git
diff showing no Securo-sourced files, with the Budget config-vs-monitoring
split left as an open decision for Dan before it becomes a claim.

## Not yet specified

- fog: Should the Budget page split into a separate "configure limits" table
  view and a "track spending" progress view (Securo's pattern), or stay
  merged as OfflineBudget currently has it? Statable but not yet decided —
  needs Dan's call before it can become an ISC. See
  `docs/securo-comparison.md` § Budgets (setup) page.
- fog: Exact hex values, spacing units, and border-radius figures for the
  visual-uplift claims below are sourced from static screenshot inspection,
  not a live-rendered pass. A live Interceptor walkthrough of
  `demo.usesecuro.com` (blocked this session — `INTERCEPTOR_TEST_CONTEXT_ID`
  not configured on this machine) would sharpen F1/F2/F4/F5 from "directionally
  right" to "pixel-verified." Not required to start building, but should
  happen before final polish/close.
- fog: What specifically about the shipped visual changes didn't match what
  Dan wanted — he rolled the code back (2026-08-24) without specifying which
  parts read wrong. Needs a conversation before re-attempting any of
  F1–F8 (see Decisions).

## Features

### F1 · Chart vocabulary audit
Why: Securo deliberately restricts itself to stat tiles, progress bars, and
one dual-line time series — no pies/donuts/treemaps. OfflineBudget already
has a Sankey (keep it) and other chart types; done means every chart on every
page has been checked against this restrained bar and anything busier than
necessary is either simplified or justified.

- [ ] ISC-1: A written audit note (`docs/securo-comparison.md` or a new
      `docs/chart-audit.md`) lists every chart component currently rendered
      across `frontend/src/pages/*.tsx` with its chart type, and marks each
      as keep/simplify/no-change (file-exists + manual content check)
- [ ] ISC-2: No new chart type is introduced anywhere in this ISA's changes
      that isn't already one of: stat tile, progress bar, single/dual-line
      time series, or the existing Sankey (grep diff for new chart imports)

### F2 · Category progress bars
Why: Budget category rows should read at a glance — spent/of-budgeted amount,
horizontal bar, color shift on breach — matching the clarity of Securo's
pattern without copying its code.

- [ ] ISC-3: `frontend/src/pages/Budget.tsx` (or a new
      `CategoryProgressBar.tsx` component it imports) renders a horizontal
      progress bar per budget category showing spent-of-limit (grep for a
      progress-bar element/component in the diff)
- [ ] ISC-4: The progress bar's fill color changes based on spend ratio —
      under ~80% one color, 80–100% a warning color, over 100% a breach color
      (grep for a ratio-based conditional class/style)
- [ ] ISC-5: Each progress bar row shows "R$X of R$Y"-equivalent subtext
      (amount spent of amount budgeted) beneath or beside the bar (grep JSX
      for the spent/limit text pairing)
- [ ] ISC-6: Component works in both dark and light mode (grep `dark:` near
      the progress-bar styling)

### F3 · Dashboard stat header (reconciled, not copied)
Why: Securo leads with 4+ stat tiles; OfflineBudget's identity is one
headline number with detail a click away. Done means the dashboard gets a
compact stat row that respects that identity — fewer tiles, headline number
still visually dominant — rather than importing Securo's density wholesale.

- [ ] ISC-7: `frontend/src/pages/Dashboard.tsx` stat row shows no more than 3
      stat tiles alongside the existing headline number, not 4+ (manual
      count against the rendered component / grep count of stat-tile JSX
      blocks)
- [ ] ISC-8: The existing headline "Available to Spend"-style number remains
      visually largest on the page (unchanged font-size class or larger,
      confirmed by diff not shrinking it)
- [ ] ISC-9: Anti: the dashboard does not add a Securo-style multi-line
      "by currency" or "owed to you" sub-breakdown unless Phase 2 splitting
      work (out of scope here) has shipped first (grep diff for premature
      cross-feature UI)

### F4 · Dark/light parity
Why: Both themes should get equal design attention, not dark-as-primary and
light-as-afterthought.

- [ ] ISC-10: Every component touched by F1–F8 has a `dark:` Tailwind variant
      (or dark-aware CSS) for every new color/background introduced (grep
      diff: each new `bg-`/`text-`/`border-` class touched has a paired
      `dark:` class)
- [ ] ISC-11: A manual check (screenshot or visual read) confirms no new
      element is illegible or missing contrast in either theme (manual —
      logged in Verification, not automatable via grep)

### F5 · Spacing/density pass
Why: Match Securo's "generous padding, moderate-to-high but well-gutted"
density — tighten anything currently cramped or overly sparse without
copying exact values.

- [ ] ISC-12: At least one existing page's card/container padding is measured
      against the current Tailwind spacing scale and adjusted where it
      diverges most from a consistent rhythm (grep diff shows updated
      padding/margin classes on at least one page)
- [ ] ISC-13: Anti: no page's information density increases to the point that
      more scrolling is required than before this ISA (manual check against
      F7)

### F6 · Nav flattening
Why: Securo's sidebar is flat with most sections one click away. Confirm
OfflineBudget's nav doesn't bury anything unnecessarily deep.

- [ ] ISC-14: A written nav-depth audit (in Decisions or a short note) lists
      every top-level and nested route in `frontend/src/components/Layout.tsx`
      with its click-depth from the sidebar, and flags anything more than one
      click deep that doesn't need to be (manual audit, logged)
- [ ] ISC-15: Any route flagged as unnecessarily buried in ISC-14 is promoted
      to a top-level sidebar item (grep diff of `Layout.tsx` nav array)

### F7 · Fit-to-viewport, no-scroll page layout
Why: Securo composes pages to fit one screen height (fixed header/tab zone,
cards sized to fill remaining space) rather than scrolling indefinitely. This
is a structural layout change, not a spacing tweak.

- [ ] ISC-16: `frontend/src/pages/Dashboard.tsx`'s top-level container uses a
      height-constrained layout (e.g. `h-screen`/`h-full` + flex/grid with
      `overflow-hidden` on the outer shell) rather than natural document flow
      (grep for viewport-height layout classes in the diff)
- [ ] ISC-17: Any card whose content would overflow its allotted space scrolls
      internally (`overflow-y-auto` on the card, not the page) rather than
      pushing the page taller (grep for internal-scroll classes on at least
      one card)
- [ ] ISC-18: A manual check at a common viewport size (e.g. 1440×900)
      confirms the Dashboard requires no vertical page scroll (manual,
      logged in Verification)
- [ ] ISC-19: Anti: no page becomes *less* usable on a smaller viewport
      (e.g. 1280×800) as a result of the height-constrained layout — internal
      scroll areas must still be reachable (manual check)

### F8 · Plain-language pacing sentence
Why: Directly matches Dan's long-standing #1 forecast priority — replace a
chart the user has to eyeball for negative-balance risk with a computed
sentence. Securo's version ("At this pace, you'll spend R$X by month end") is
spend-pace framed; OfflineBudget's existing forecast priority is
balance-negative framed — this claim adapts the *mechanism* (a sentence, not
a chart), not the exact wording.

- [ ] ISC-20: `frontend/src/pages/Dashboard.tsx` (or the existing forecast
      summary component) renders a single computed sentence describing
      projected checking-balance risk this month, sourced from the existing
      forecast/Safety-Margin calculation already in the backend (grep for the
      new sentence-rendering JSX)
- [ ] ISC-21: The sentence updates based on real forecast data — not a static
      string (grep confirms it interpolates a computed value, e.g. a date or
      dollar amount from forecast state)
- [ ] ISC-22: Anti: no new financial calculation logic is introduced in the
      backend for this claim — the sentence consumes an existing computed
      value (git diff --name-only shows no new/changed files under
      `backend/` for this ISC, or if a field is added it's a formatting
      pass-through of an existing calculation, confirmed in Decisions)
- [ ] ISC-23: The sentence is visually adjacent to (not replacing) the
      existing Safety Margin / Spendable-this-week display, since those
      metrics answer a different question per prior product decisions (manual
      check against existing Dashboard layout)

### F0 · Cross-cutting

- [ ] ISC-24: `npx tsc --noEmit` exits 0 in `frontend/` after all F1–F8
      changes (bash)
- [ ] ISC-25: Anti: no file under `backend/` is modified except as explicitly
      permitted by F8/ISC-22 (git diff --name-only)
- [ ] ISC-26: Anti: no file, asset, or string literal copied verbatim from
      `github.com/securo-finance/securo` appears anywhere in the diff — every
      new component is original OfflineBudget code (manual review of diff
      against `docs/securo-comparison.md`'s license note)
- [ ] ISC-27: Anti: no new dependency on a charting library beyond what
      `frontend/package.json` already includes is added without an explicit
      Decisions entry justifying it (grep `package.json` diff)
- [ ] ISC-28: All claims above render correctly in both dark and light mode
      (rollup check — see F4/ISC-10, ISC-11)
- [x] ISC-29: Dan has reviewed this ISA before any implementation work begins
      (manual — Dan's explicit go-ahead, logged in Decisions)

## Test Strategy

| isc | type | check | threshold | tool | anchors_to |
|-----|------|-------|-----------|------|------------|
| ISC-1 | manual | audit note exists and lists all chart components | present | Read | F1 |
| ISC-2 | grep | new chart-library imports in diff | 0 unexpected | Grep | F1 |
| ISC-3 | grep | progress-bar element/component in Budget.tsx diff | 1+ match | Grep | F2 |
| ISC-4 | grep | ratio-based conditional class near progress bar | 1+ match | Grep | F2 |
| ISC-5 | grep | spent/limit text pairing in JSX | 1+ match | Grep | F2 |
| ISC-6 | grep | `dark:` near progress-bar styling | 1+ match | Grep | F2 |
| ISC-7 | manual | count of stat-tile JSX blocks in Dashboard.tsx | ≤3 | Read | F3 |
| ISC-8 | manual | headline number font-size class unchanged or larger | confirmed | Read | F3 |
| ISC-9 | grep | Securo-style by-currency/owed-to-you block in diff | 0 matches | Grep | F3 |
| ISC-10 | grep | `dark:` variant paired with each new color class | 1:1 pairing | Grep | F4 |
| ISC-11 | manual | visual read in both themes | no contrast issues | Read | F4 |
| ISC-12 | grep | updated padding/margin classes in diff | 1+ match | Grep | F5 |
| ISC-13 | manual | scroll-height comparison before/after | not increased | Read | F5 |
| ISC-14 | manual | nav-depth audit note | present, logged | Read | F6 |
| ISC-15 | grep | `Layout.tsx` nav array diff | matches ISC-14 flags | Grep | F6 |
| ISC-16 | grep | viewport-height layout classes in Dashboard.tsx diff | 1+ match | Grep | F7 |
| ISC-17 | grep | internal-scroll class on at least one card | 1+ match | Grep | F7 |
| ISC-18 | manual | no page scroll at 1440×900 | confirmed | Read | F7 |
| ISC-19 | manual | usable at 1280×800 | confirmed | Read | F7 |
| ISC-20 | grep | new sentence-rendering JSX in Dashboard.tsx | 1+ match | Grep | F8 |
| ISC-21 | grep | interpolated computed value in sentence | 1+ match | Grep | F8 |
| ISC-22 | git | `git diff --name-only` backend/ changes | 0 unless justified | Bash | F8 |
| ISC-23 | manual | sentence placed adjacent to Safety Margin display | confirmed | Read | F8 |
| ISC-24 | build | `cd frontend && npx tsc --noEmit` | exit 0 | Bash | F0 |
| ISC-25 | git | `git diff --name-only` backend/ paths | 0 unless F8-justified | Bash | F0 |
| ISC-26 | manual | diff review against Securo source | no verbatim copies | Read | F0 |
| ISC-27 | grep | `package.json` diff for new chart deps | 0 unless justified | Grep | F0 |
| ISC-28 | manual | rollup dark/light check | confirmed | Read | F0 |
| ISC-29 | manual | Dan's explicit go-ahead | confirmed | Read | F0 |

## Decisions

- 2026-08-20: New task-scoped ISA written at project-ISA home (`ISA.md`),
  superseding the completed 2026-05-07 Tier 3 Visual Polish ISA per project
  convention — git history preserves the prior content (`git log -- ISA.md`).
- 2026-08-20: Scope locked to Phase 1 (frontend/visual) from
  `docs/securo-comparison.md`'s phased plan. Phase 2 feature work
  (household splitting, investment tracking, CC billing-cycle grouping, 2FA)
  deliberately excluded — separate future ISA.
- 2026-08-20: Securo's Cash Flow report is not adopted — redundant with
  OfflineBudget's existing day-by-day Forecast page (per
  `docs/securo-comparison.md` § Real gaps).
- 2026-08-20: Budget page config-vs-monitoring split left as fog, not a
  claim — needs Dan's decision before it's scoped (see Not yet specified).
- 2026-08-20: Phase 8's pacing sentence is scoped to *reuse* existing
  forecast/Safety-Margin computation, not introduce new financial logic —
  keeps this ISA frontend-only per Constraints.
- 2026-08-20: Dan gave explicit go-ahead to build ("I am good to move to
  build"). ISC-29 checked, `phase` moved to `climbing`.
- 2026-08-20: Build attempt #1 (Forge) failed clean at startup — codex CLI
  not installed on this machine, zero writes.
- 2026-08-20: Build attempt #2 (Engineer) failed at startup — that agent
  forces worktree isolation by default, which errors because the session
  root (`~/Programming`) isn't itself a git repo.
- 2026-08-20: Build attempt #3 (general-purpose agent, no isolation, working
  directly on `main` per repo convention) completed 24/29 ISCs across 8
  commits: F6 audit (no change needed), F7 fit-to-viewport Dashboard layout,
  F3 trimmed stat row, F8 `PacingSentence` component (pure formatting
  pass-through of `budget-snapshot` fields, zero backend changes), F2
  `CategoryProgressBar` extracted into Budget.tsx, F1 chart audit (removed
  dead pie/donut code in Spending.tsx as a byproduct), F4 dark-parity grep
  audit, F5 padding consistency pass. Remaining 5 ISCs needed live-browser
  verification, blocked on Interceptor setup.
- **2026-08-24: Dan reviewed the shipped result and said it "didn't reflect
  what I wanted" and asked to reverse the visual changes.** All 8 commits
  from attempt #3 were unpushed and sat cleanly on top of `origin/main`
  (0 behind, 8 ahead, nothing else landed in between), so
  `git reset --hard` to the pre-build commit cleanly reverted all code with
  no side effects on other work. `phase` moved back to `scoping`,
  `progress` reset to 1/29 (only ISC-29's approval-to-build survives as
  still-true), and every F1–F8 checkbox reopened. What specifically read
  wrong was not captured before the revert — logged as fog; needs a
  conversation before any re-attempt so the next pass doesn't repeat the
  same miss blind.
