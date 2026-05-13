---
task: "Phase 1 Tier 3 Visual Polish — SparkLine + Dashboard"
slug: 20260507-offlinebudget-phase1-tier3
project: OfflineBudget
effort: E3
effort_source: classifier
phase: complete
progress: 34/34
mode: interactive
started: 2026-05-07T00:00:00Z
updated: 2026-05-07T00:00:00Z
---

## Problem

OfflineBudget Phase 1 Visual Polish Tier 1 and Tier 2 are complete — charts use AreaChart with gradients, ProgressRing and TrendBadge components exist, Goals page uses rings, Spending page uses activeShape, Recurring page has frequency badges and cash flow card. Tier 3 is the remaining gap: the Dashboard stat cards lack stagger animations, TrendBadge is not wired to any Dashboard data, there is no SparkLine component, and the Available to Spend card has no hero gradient treatment.

## Vision

Opening the dashboard feels like a polished financial app — stat cards slide in with stagger timing, a subtle gradient hero card anchors the "Available to Spend" section, and the Net Position card shows a tiny inline sparkline + trend badge that instantly communicates direction without needing to navigate away. The visual hierarchy makes the most important number (available cash) feel prominent.

## Out of Scope

New backend endpoints for sparkline data are not included — sparklines consume the existing `/spending/rolling-monthly` endpoint already available in the frontend. This task does not touch any backend Python files. Phase 2 (AI Agent) and Phase 3+ are out of scope. No changes to any existing chart page (Forecast, NetWorth, Spending, Goals, Budget, Recurring).

## Constraints

- SparkLine.tsx must be pure SVG — no Recharts, no D3, no charting libraries.
- TrendBadge wiring uses only data already fetched or fetched via existing API endpoints.
- All visual changes must work in both dark and light mode.
- Zero new TypeScript errors (`npx tsc --noEmit` must pass after changes).
- Do not modify any file outside `frontend/src/` or create new backend files.

## Goal

Create `SparkLine.tsx` (pure SVG, 64px default width), update the Dashboard to import and use TrendBadge + SparkLine on stat cards with stagger animation, apply a hero gradient to the Available to Spend card, wire MoM percentage to TrendBadge on Net Position using `rollingMonthly` data, and verify zero TypeScript errors and correct dark/light mode rendering.

## Criteria

- [x] ISC-1: `frontend/src/components/SparkLine.tsx` file exists
- [x] ISC-2: SparkLine accepts `data: number[]` as a required prop (grep interface)
- [x] ISC-3: SparkLine accepts optional `width` prop defaulting to 64 (grep default)
- [x] ISC-4: SparkLine accepts optional `height` prop defaulting to 32 (grep default)
- [x] ISC-5: SparkLine renders an `<svg>` element containing a `<polyline>` or `<path>` (grep)
- [x] ISC-6: SparkLine renders a gradient fill element (`<defs>` + `<linearGradient>`) (grep)
- [x] ISC-7: SparkLine renders a final-value dot (`<circle>` at last data point) (grep)
- [x] ISC-8: SparkLine returns null when `data.length < 2` (grep early-return)
- [x] ISC-9: SparkLine is exported as a named export `export function SparkLine` (grep)
- [x] ISC-10: SparkLine uses CSS variable or dark-aware class for stroke color (grep `dark:`)
- [x] ISC-11: `Dashboard.tsx` imports TrendBadge from `../components/TrendBadge` (grep)
- [x] ISC-12: `Dashboard.tsx` imports SparkLine from `../components/SparkLine` (grep)
- [x] ISC-13: `Dashboard.tsx` calls `analyticsApi.rollingMonthly(6)` via useQuery (grep)
- [x] ISC-14: `Dashboard.tsx` computes `momPct` (current-month vs prior-month spending from rollingMonthly) (grep `momPct`)
- [x] ISC-15: Net Position stat card renders `<TrendBadge pct={momPct} inverse />` (grep)
- [x] ISC-16: At least one Dashboard stat card renders `<SparkLine data={sparkData} />` (grep)
- [x] ISC-17: Dashboard stat card grid div has `animate-fade-slide-up` on each card (grep)
- [x] ISC-18: Stat cards in the 4-card grid use stagger delay classes (grep `animate-delay-`)
- [x] ISC-19: Available to Spend card has a gradient background class or inline style (grep `gradient\|from-indigo\|bg-gradient`)
- [x] ISC-20: Available to Spend gradient is dark-mode-aware (grep `dark:` near gradient)
- [x] ISC-21: Net Position stat card uses dynamic `stat-card-accent-green` or `stat-card-accent-red` class (grep)
- [x] ISC-22: Checking stat card uses `stat-card-accent-indigo` or similar fixed accent (grep `stat-card-accent`)
- [x] ISC-23: `npx tsc --noEmit` exits 0 in the frontend directory (bash)
- [x] ISC-24: SparkLine TypeScript interface has no `any` types (grep `any` in SparkLine.tsx)
- [x] ISC-25: `analyticsApi.rollingMonthly` is already defined in `frontend/src/api/index.ts` (grep — no new API method needed)
- [x] ISC-26: SparkLine has no import from `recharts` or `d3` (grep)
- [x] ISC-27: Anti: No Python files in `backend/` are modified (git diff --name-only)
- [x] ISC-28: Anti: No new API endpoint is added to backend (git diff --name-only confirms no backend changes)
- [x] ISC-29: Anti: `Forecast.tsx`, `NetWorth.tsx`, `Spending.tsx`, `Goals.tsx`, `Budget.tsx` are unchanged (git diff --name-only)
- [x] ISC-30: Animation delay classes `animate-delay-100` through `animate-delay-400` exist in `index.css` (grep)
- [x] ISC-31: `progress-fill` in `index.css` retains `cubic-bezier(0.34, 1.56, 0.64, 1)` spring timing (grep)
- [x] ISC-32: SparkLine color prop defaults to `#6366f1` (indigo, consistent with brand) (grep)
- [x] ISC-33: SparkLine uses `useId()` or stable unique key for `<linearGradient id>` to prevent multi-instance ID collision (grep `useId`)
- [x] ISC-34: SparkLine guards against flat data — when min === max, uses a safe fallback Y range (grep `min === max` or epsilon logic)

## Test Strategy

| isc | type | check | threshold | tool |
|-----|------|-------|-----------|------|
| ISC-1 | file-exists | `ls frontend/src/components/SparkLine.tsx` | exits 0 | Bash |
| ISC-2 | grep | `data: number\[\]` in SparkLine.tsx | 1+ match | Grep |
| ISC-3 | grep | `width = 64` in SparkLine.tsx | 1+ match | Grep |
| ISC-4 | grep | `height = 32` in SparkLine.tsx | 1+ match | Grep |
| ISC-5 | grep | `<svg` and `polyline\|path` in SparkLine.tsx | 1+ match each | Grep |
| ISC-6 | grep | `linearGradient` in SparkLine.tsx | 1+ match | Grep |
| ISC-7 | grep | `<circle` in SparkLine.tsx | 1+ match | Grep |
| ISC-8 | grep | `data.length < 2` return null in SparkLine.tsx | 1+ match | Grep |
| ISC-9 | grep | `export function SparkLine` in SparkLine.tsx | 1+ match | Grep |
| ISC-10 | grep | `dark:` in SparkLine.tsx | 1+ match | Grep |
| ISC-11 | grep | `import.*TrendBadge` in Dashboard.tsx | 1+ match | Grep |
| ISC-12 | grep | `import.*SparkLine` in Dashboard.tsx | 1+ match | Grep |
| ISC-13 | grep | `rollingMonthly` in Dashboard.tsx | 1+ match | Grep |
| ISC-14 | grep | `momPct` in Dashboard.tsx | 1+ match | Grep |
| ISC-15 | grep | `TrendBadge` in Dashboard.tsx JSX | 1+ match | Grep |
| ISC-16 | grep | `SparkLine` in Dashboard.tsx JSX | 1+ match | Grep |
| ISC-17 | grep | `animate-fade-slide-up` in stat-card divs in Dashboard.tsx | 1+ match | Grep |
| ISC-18 | grep | `animate-delay-` in Dashboard.tsx | 2+ match | Grep |
| ISC-19 | grep | `gradient\|from-indigo\|bg-gradient` in Dashboard.tsx | 1+ match | Grep |
| ISC-20 | grep | `dark:` near gradient in Dashboard.tsx | 1+ match | Grep |
| ISC-21 | grep | `stat-card-accent-green\|stat-card-accent-red` in Dashboard.tsx dynamically | 1+ match | Grep |
| ISC-22 | grep | `stat-card-accent` in Dashboard.tsx | 2+ match | Grep |
| ISC-23 | build | `cd frontend && npx tsc --noEmit` | exit 0 | Bash |
| ISC-24 | grep | no `any` in SparkLine.tsx | 0 matches | Grep |
| ISC-25 | grep | `rollingMonthly` in api/index.ts | 1+ match | Grep |
| ISC-26 | grep | no `recharts\|d3` in SparkLine.tsx | 0 matches | Grep |
| ISC-27 | git | `git diff --name-only` no `backend/` paths | 0 backend files | Bash |
| ISC-28 | git | `git diff --name-only` no Python files | 0 `.py` files | Bash |
| ISC-29 | git | `git diff --name-only` no Forecast/NetWorth/Spending/Goals/Budget | 0 matches | Bash |
| ISC-30 | grep | `animate-delay-100` and `animate-delay-400` in index.css | 1+ each | Grep |
| ISC-31 | grep | `cubic-bezier(0.34, 1.56, 0.64, 1)` in index.css | 1+ match | Grep |
| ISC-32 | grep | `#6366f1` default in SparkLine.tsx | 1+ match | Grep |

## Features

| name | description | satisfies | depends_on | parallelizable |
|------|-------------|-----------|------------|----------------|
| SparkLine component | Create pure-SVG SparkLine.tsx with gradient fill, dot, dark mode, guard | ISC-1 through ISC-10, ISC-24, ISC-26, ISC-32 | none | true |
| Dashboard TrendBadge wiring | Import TrendBadge+SparkLine, add rollingMonthly query, compute momPct, render in Net Position card | ISC-11 through ISC-16, ISC-25 | SparkLine component | false |
| Dashboard stat card polish | Add stagger animation, stat-card-accent classes, hero gradient to ATS card | ISC-17 through ISC-22, ISC-30 | none | true |
| TypeScript verification | Confirm zero type errors after all changes | ISC-23 | Dashboard TrendBadge wiring, SparkLine component | false |
| Regression guard | Confirm backend untouched, other pages untouched, animation CSS intact | ISC-27 through ISC-31 | all above | false |

## Decisions

- 2026-05-07: Tier 1+2 confirmed complete from codebase scan. Scope narrowed to Tier 3 only.
- 2026-05-07: SparkLine uses existing `rollingMonthly` endpoint — no new backend needed.
- 2026-05-07: momPct computed client-side from last two months in rollingMonthly array.
- 2026-05-07: Project ISA home chosen at `<project>/ISA.md` per v6.2.0 doctrine.
