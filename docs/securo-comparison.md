# Competitive Reference: Securo

> Research notes for future spec'ing. Not a roadmap commitment — cross-check
> against [future-work.md](future-work.md) before spec'ing anything below, since
> several items here turned out to already be shipped or already planned.
>
> **Progress since this doc was written (2026-08-20):** the "Navigation Shell"
> sub-project shipped the month/year popover picker, Account Detail page,
> sidebar account list, and regrouped Settings. Separately, 2026-08-31 shipped:
> global balance/last-four masking with a header eye-toggle, dark-mode toggle
> moved next to it, a shared `ConfirmDialog` on destructive actions, and a
> sidebar accounts-section redesign (type subtitle per row, header-level total
> + collapse chevron replacing the old "+N more" link, stacked balance/%-badge,
> user identity relocated to a footer card above Sign Out — matching Securo's
> sidebar footer pattern, minus the multi-tenant-only "Update Available"
> indicator and workspace switcher, which don't apply to a single-admin
> self-hosted app). Re-verify anything below against current code before
> treating it as still-outstanding — this doc is a snapshot, not live state.

**Subject:** [usesecuro.com](https://www.usesecuro.com/en) · [github.com/securo-finance/securo](https://github.com/securo-finance/securo)
**Researched:** 2026-08-19, three passes (features/budgeting model, bank sync/reports, visual design/deployment)
**License:** AGPL-3.0 — see [Licensing caveat](#licensing-caveat) before borrowing any code or schema.

## Snapshot

Self-hosted-only, no-cloud-tier open-source money manager. FastAPI + PostgreSQL +
Redis/Celery backend, React/TypeScript/Vite/Tailwind frontend, Docker Compose or
Helm deploy. Solo maintainer (Tássio Noronha), repo created 2026-03-08 (~5 months
old), 1.8k GitHub stars but only 9 watchers — read that as launch-traffic spike,
not deep operational adoption. No revenue model; pricing page is a joke $0.00
invoice. Same category and same privacy pitch as OfflineBudget — closest public
analogue found.

## Already shipped or already planned in OfflineBudget — corrections to the initial scan

The first research pass flagged these as Securo advantages before checking
`future-work.md` against them. They are not gaps:

| Feature | OfflineBudget status |
|---|---|
| Rules engine (auto-categorization) | ✅ Shipped — contains/startswith/regex |
| Sankey income-to-expense diagram | ✅ Shipped |
| Credit card tracking (due dates, utilization) | ✅ Shipped |
| Multi-user (admin / view-only roles) | ✅ Shipped |
| Budget rollover (backend) | ✅ Shipped, but **not surfaced in UI** — `rollover_enabled`/`rollover_balance` exist on `Category`, no visible indicator. Medium-priority item already in future-work.md. |
| Bank sync beyond manual import | 🔜 Planned — Plaid, high priority in future-work.md (Securo uses SimpleFIN/Enable Banking/Pluggy instead of Plaid; worth reading their approach before committing to Plaid, see [Bank sync](#bank-sync-approach) below) |
| Split transactions (across categories) | 🔜 Planned, medium priority — different from Securo's split, see below |
| Multi-household isolation | 🔜 Planned, lower priority — matches Securo's "Workspaces" |

## Real gaps — Securo has, OfflineBudget doesn't

| Feature | Securo detail | Effort/value read |
|---|---|---|
| **Household expense splitting** | "Groups" — equal/exact/percentage splits between *people* sharing a workspace, "Total moved / Owed to you / You owe" cards, Settle-up flow. This is distinct from OfflineBudget's planned category-split feature (splitting one transaction across budget categories, not across people). | High value — directly matches Dan's stated need for wife-visible shared reporting; genuinely new capability, not overlapping planned work. |
| **Investment/asset tracking** | 9 asset types, manual/growth-rule/live-ticker valuation, buy/sell log with cost basis and realized/unrealized gains. | Medium — OfflineBudget has net worth tracking but no live portfolio valuation. |
| **Credit-card billing-cycle grouping** | Statement close/due day fields group each purchase into the correct statement automatically. | Low effort, decent value — OfflineBudget tracks due dates/utilization but not automatic cycle-based purchase grouping. |
| **Cash Flow report (forward projection)** | Distinct from OfflineBudget's day-by-day Forecast: projects starting balance → inflow → outflow → ending balance at 3/6/12-month grain, report-style rather than day-by-day chart. | Low — largely redundant with existing Forecast; only worth it if Dan wants a coarser monthly summary view. |
| **2FA / passkeys / OIDC** | TOTP with brute-force protection, WebAuthn passkeys, OIDC login. | Medium — auth hardening, no OfflineBudget equivalent noted. |
| **AI chat agent over budget data** | Conversational agent (Ollama/OpenAI/Anthropic) with RAG document upload. **Caveat: verified only in marketing mockups (English/USD), not in the real product screenshots (Portuguese/BRL) — may be partly aspirational.** | Low priority, unverified feature — don't spec from marketing copy alone; check the live demo first if pursued. |
| **Multi-currency (auto FX)** | Open Exchange Rates conversion. | Low — likely irrelevant to Dan's single-currency household use. |
| **Collections** (cross-cutting account groupings, e.g. "how's the emergency fund doing") | Filters the whole app by a named group of accounts/wallets. | Low-medium — could map onto OfflineBudget's Money Market emergency-fund exclusion logic as a generalized feature. |

## What OfflineBudget has that Securo doesn't

- **Zero-based-adjacent methodology gap**: Securo is limit-based/monthly-cap only — no envelopes, no true rollover exposed in UI (though the field exists server-side, same gap as ours), no scenario planning. OfflineBudget's Budget Scenario Planning has no Securo equivalent at all.
- **Tax Estimator** — full 2025 federal + state, itemized vs. standard, bracket ladder, FICA. Nothing comparable in Securo's docs.
- **Reconciliation** with recurring-item linking and quarterly checkpoints.
- **CLI** with direct DB access (`cli/budget.py`) — Securo has no CLI, web UI + Docker/Helm only.
- **Discretionary vs. fixed spend framing** as an explicit UX philosophy (Spendable-this-week / Safety Margin) — Securo's dashboard is metric-density-driven without that split.
- **Daily email summary** — Securo has no equivalent scheduled report mentioned in docs.

## Design philosophy divergence

Securo optimizes for **information density**: a 4+ metric stat header, category progress bars, one dual-line balance chart, moderate-to-high card density (closer to Monarch than YNAB's spreadsheet grid). Restrained chart vocabulary — no pies/donuts/treemaps. Indigo `#6366F1` accent, green/red semantic for in/out, both dark and light mode fully first-class (paired screenshots, in-app toggle).

OfflineBudget's existing philosophy is **progressive disclosure**: one headline number (e.g. "how much is left this month"), detail one click away. Worth deciding explicitly whether to hold this line as gaps get closed, since several candidate features above (Collections, Cash Flow report) pull toward Securo's denser style.

## Bank sync approach

Securo deliberately avoids Plaid. Three region-specific aggregators, each requiring
the *user's own* registered credentials with the third party (not Securo's):
SimpleFIN (US, ~$1.50/mo, Basic Auth on an unguessable Access URL, no OAuth,
read-only, no on-demand refresh), Enable Banking (Europe/PSD2, ~2,500 banks, free
restricted tier), Pluggy (Brazil). Background sync runs hourly, refreshing any
connection stale >4 hours, plus manual per-connection sync. Fully manual/offline
operation (OFX/CSV/QIF/CAMT import with duplicate detection) is a documented
first-class path, not a fallback.

Relevant to OfflineBudget's planned Plaid integration: Plaid is the
higher-coverage, higher-cost, more "vendor in the middle" option. SimpleFIN in
particular is worth a look as a cheaper, lower-friction, US-focused alternative
before committing to Plaid's `PLAID_CLIENT_ID`/`PLAID_SECRET` integration path.

## Security implementation notes (source-verified, not just marketing)

A fourth pass read actual source (`crypto.py`, `bank_connection.py`, provider
files) rather than docs/marketing. Findings relevant to OfflineBudget's own
security posture:

- Encryption at rest is narrower than the marketing implies: Fernet symmetric
  encryption, key derived via `PBKDF2-HMAC-SHA256(SECRET_KEY, hardcoded salt,
  100k iterations)`, applied only to Enable Banking session IDs and SimpleFIN
  access URLs (the SimpleFIN URL embeds Basic Auth credentials, so this matters).
  Pluggy stores only an opaque item ID in plaintext. **The rest of the database —
  transactions, balances, payees — is unencrypted.**
- `.env.example` ships `SECRET_KEY=change-me-in-production`. Since the token
  encryption key derives from it, an operator who doesn't rotate this has
  cosmetic encryption. Plaintext fallback paths also exist in the credential
  code for backward compatibility (`encrypt(x) or x`).
- "We don't have any servers" is rhetorical, not literal — they run the
  marketing site, docs, blog, and a public demo. More importantly: bank sync
  necessarily routes data through Pluggy/Enable Banking/SimpleFIN in transit,
  which the GitHub README's "not a single byte to third parties" phrasing
  overstates. The landing page itself is more careful ("brokered through
  regulated open-banking connections").
- The optional AI Agents feature (RAG + MCP tool-use over financial data) is
  the one configuration that can genuinely egress financial data to a hosted
  LLM provider if not pointed at a local model — not flagged as a tradeoff on
  the landing page.
- No third-party security audit or bug bounty found; `SECURITY.md` offers
  standard private disclosure (48hr ack, latest version only). Bus factor of
  one — 195 of the total commits are the founder's, next highest is 14.

**Takeaway for OfflineBudget**: the Fernet-keyed-off-`SECRET_KEY` pattern is a
reasonable reference *design* for encrypting stored bank tokens (do not copy
the code — see licensing caveat below) — but don't stop at token encryption;
Securo's own gap (unencrypted transaction/balance data at rest) is a mistake
worth deliberately not repeating if OfflineBudget ever stores bank credentials
directly.

## Licensing caveat

Securo is AGPL-3.0, which is viral over network use. Reading their docs for UX/feature
ideas and re-implementing independently is fine. Copying actual code, schema
definitions, or substantial structure would obligate OfflineBudget's source to be
released under AGPL too. Treat this doc as feature/design inspiration only, never
as a source to copy from.

## Phased plan

Frontend uplift first, then feature work — visual changes are cheap to
reverse and compound (every later feature ships in the improved shell instead
of getting restyled twice). Every item below is **independent re-implementation
from written notes/observation, never copied code or assets** — see
[Licensing caveat](#licensing-caveat). Pending Dan's review; nothing here is
built until approved per-phase.

### Phase 1 — Frontend/visual uplift (no schema or feature changes)

Reference direction only (confirm exact colors/spacing via a live Interceptor
pass before implementing — current detail comes from static screenshot
inspection, not interactive verification):

1. **Chart vocabulary audit** — Securo leans on stat tiles + progress bars + one
   dual-line time series, deliberately skipping pies/donuts/treemaps.
   OfflineBudget already uses a Sankey (keep it, it's a real differentiator) —
   audit remaining charts against this "restrained" bar and cut anything busier
   than it needs to be.
2. **Category progress bars** — horizontal bar per budget category, spent/of-budgeted
   subtext, color shift on breach (their pattern: green → amber near limit → red
   over). Compare against OfflineBudget's current budget-progress treatment and
   tighten if looser.
3. **Dashboard stat header** — a compact top-of-page row of 3–4 headline numbers
   before any chart. Needs to be reconciled with OfflineBudget's existing
   progressive-disclosure philosophy (see [Design philosophy divergence](#design-philosophy-divergence)) —
   likely fewer tiles than Securo's 4+, to avoid diluting the "one headline
   number" identity.
4. **Dark/light parity** — confirm both themes get equal design attention (not
   dark-as-primary-light-as-afterthought), matching Securo's paired-screenshot
   treatment.
5. **Spacing/density pass** — generous card padding, moderate-to-high but
   well-gutted information density (their reference point: closer to Monarch
   than YNAB's dense grid).
6. **Nav structure check** — Securo's sidebar is flat, ~8 top-level items, most
   sections one click away. Compare against OfflineBudget's current nav depth
   and flatten anything buried.
7. **Fit-to-viewport page layout** — pages are composed to fit one screen
   height with no vertical scroll (fixed header/tab zone, cards sized to fill
   remaining space), confirmed live on the Net Worth/Analytics page. A
   structural change, not just a spacing tweak — see the cross-page layout
   note under [Interactive component notes](#interactive-component-notes-from-live-demo-screenshots-2026-08-20).
8. **Plain-language pacing sentence** — "At this pace, you'll spend R$X by
   month end" on the dashboard. High priority: this is close to the exact
   pattern already flagged as Dan's #1 forecast ask (a computed sentence
   instead of a chart the user has to eyeball for negative-balance risk).
   Cheap to build — OfflineBudget's forecast engine already has the
   underlying projection; this is a copy/placement change, not new math.
9. **Config vs. monitoring split (open question, not yet decided)** — Securo's
   Budgets page (set the limit) is a plain table with no progress bars;
   progress bars only appear on the Dashboard (track against reality).
   OfflineBudget's Budget tab currently does both in one view. Worth a
   deliberate decision — split into two views, or keep merged — before
   touching that page's layout.

**Verification before implementation**: Interceptor's live pass is still
blocked on this machine (`INTERCEPTOR_TEST_CONTEXT_ID` not configured, one-time
setup pending). Dan captured three manual screenshots from the live demo
(`demo.usesecuro.com`, 2026-08-20) covering interactive components the
marketing screenshots never showed — notes below are from those, not static
marketing images, so treat this detail as higher-confidence than the rest of
Phase 1.

### Interactive component notes (from live demo screenshots, 2026-08-20)

**Month/year picker** (top nav, e.g. "‹ August 2026 ›"):
- Trigger is three segments: circular icon-button (‹), pill-shaped button with
  calendar icon + "Month Year" label, circular icon-button (›).
- Clicking the center pill opens a popover (white card, soft shadow, rounded
  ~16px corners) with its own year stepper ("‹ 2026 ›") above a 4-column grid
  of month abbreviations (Jan–Dec).
- Selected month gets a solid indigo fill + white bold text; hover/focus state
  on the stepper arrows shows a light purple ring outline, not a background fill.
- Reimplementable as: existing OfflineBudget month nav + a popover-triggered
  grid picker instead of (or in addition to) arrow-only stepping — faster
  jump to a specific month than clicking through arrows one at a time.

**Workspace/settings dropdown** (bottom-left nav):
- Grouped menu with dividers, not a flat list: workspace actions (Workspace
  settings, New workspace) → account/security (Change password, Two-Factor
  Auth, Passkeys) → app-level (Backup, Check for updates, Language with a
  submenu chevron) → destructive (Logout, red text+icon, own divider above it).
- Below the popover: persistent workspace switcher showing avatar-square,
  workspace name, account email, role badge (truncated "OWN…"), and an
  up/down chevron — always visible, not buried in the menu itself.
- Version number pinned at the very bottom of the sidebar.
- Reimplementable pattern: grouping settings by *who it affects* (workspace →
  account → app → destructive) with dividers and color-coding the destructive
  action, rather than one long flat settings list — worth applying to
  OfflineBudget's own Settings navigation regardless of the multi-workspace
  question.

**Net Worth / Analytics page**:
- Report-switcher is underlined text tabs (Net Worth / Income vs Expenses /
  Cash Flow / Money Map), not a dropdown or sidebar sub-nav — keeps all four
  reports one click apart from each other.
- Top-right range control is two paired button groups: coarse range
  (6M/YTD/1Y/2Y) + granularity (D/W/M/Y), both as segmented pill buttons with
  the active choice solid-indigo-filled.
- Summary card: one big headline number (net worth) with a small "+/- vs start
  of period" subtext directly under it, and three smaller color-keyed stats
  (Accounts/Assets/Liabilities) laid out to the right on the same card — same
  "headline number first, detail alongside" instinct as OfflineBudget's own
  philosophy, just denser.
- Main chart is a single-line area chart (solid line, soft fill beneath) with
  a hover tooltip that shows date + value + period-over-period change in a
  small floating card — clean, minimal, no gridlines clutter.
- Below the main chart, two cards side by side: a donut/composition chart with
  the total re-stated in its center hole and a tabbed toggle (Net Worth /
  Assets & Accounts / Liabilities) to recompute the same donut for a different
  slice, legend below with a "+5 more" overflow link instead of listing every
  segment; and a stacked-bar "Evolution" chart (assets/liabilities as stacked
  bars per month) with a dashed net-worth line overlaid on top.
- Reimplementable patterns: text-tab report switcher, paired
  range+granularity segmented controls, donut-with-center-total, and
  "+N more" as the standard legend-overflow treatment instead of a long list.

**Main Dashboard**:
- Sidebar nav is grouped by workflow stage via small-caps section labels —
  ACCOUNTS (Transactions, Accounts) → ANALYSIS (Reports, Assets) → SETUP
  (Budgets, Goals, Recurring, Categories, Payees, Groups, Rules). Different
  grouping logic than the settings dropdown (which groups by who it affects) —
  worth keeping both patterns distinct rather than merging them.
- Global search with a `⌘K` shortcut hint sits at the very top of the sidebar,
  above the nav groups.
- Header row: a soft greeting ("Good evening") over the page title
  ("August 2026"), month-nav on the right — same arrow+pill pattern as the
  Analytics page.
- Summary card pairs a big headline stat (Savings Rate, 76%, green) with four
  smaller labeled stats in a row (Total Balance w/ info-icon tooltip, Monthly
  Income in green, Monthly Expenses in red, Assets in blue), plus two
  sub-lines: a by-currency breakdown and a "Net R$X including R$Y owed to you"
  line — the "owed to you" figure is the split-transaction/Groups balance
  surfaced right on the dashboard, not buried in a separate page.
- **Directly relevant to Dan's own stated priority**: a plain-language pacing
  line under the summary stats — *"At this pace, you'll spend R$4.516,50 by
  month end."* This is close to the exact proactive-callout pattern flagged in
  memory as the #1 priority for OfflineBudget's forecast (evolving the passive
  red dashed zero-line into an active "projected negative on Aug 20"-style
  statement). Securo's version is spend-pace framed rather than
  balance-negative framed, but the UI mechanism — a computed sentence, not a
  chart the user has to interpret — is the pattern worth adopting directly.
- A separate "All caught up! All transactions are categorized" status widget
  with a green checkmark circle sits beside the summary card — a zero-inbox-style
  affordance that turns "everything is categorized" into a visible done-state
  rather than an absence of a warning.
- **Spending by Category** card: sortable via a "Highest first" text control
  (top right of the card, not a separate settings screen), rows are
  icon+name+amount+%-change-badge+progress-bar+"of R$X" subtext (same
  progress-bar treatment as the Analytics page notes above). The card scrolls
  internally when content overflows rather than growing the page — consistent
  with the fit-to-viewport principle below.
- **Balance Flow** card: dated range as a subtitle, a large colored delta
  top-right (+R$9.074,31, green), solid line + soft fill for the current
  period with a dashed gray comparison line for the prior period overlaid on
  the same axes, and a specific textual annotation below the chart ("In July
  on day 21: R$20.373,77 (+46.6%) ▲") — narrating one concrete comparison
  point in words, not just relying on hover-to-discover.
- **Goals Progress** card: "View all goals →" link, each row shows
  icon + name + "R$X / R$Y" progress + a pace label under the bar ("Ahead",
  green text) alongside the required monthly contribution rate.
- Sidebar footer: expandable account-balance list (with per-account % change),
  "+1 more" overflow, an "Update Available" indicator with a status dot, then
  the workspace switcher and version number from the earlier settings-menu
  screenshot — this whole footer block is a fixed and reused across pages.
- Small header-bar detail: a hide-balances eye-toggle and dark-mode toggle
  sit next to the logo — worth considering given privacy is core to
  OfflineBudget's positioning too (quick way to hide numbers before
  screen-sharing).

**Budgets (setup) page**:
- Deliberately plain: a single table (Category icon+name, Limit, Actions)
  with a primary "+ Add Budget" button, edit/delete icons per row. No progress
  bars here — those only appear on the Dashboard's live-tracking view. That
  split is a real pattern worth naming: **configuration screens show the
  number you set; monitoring screens show the number relative to reality.**
  OfflineBudget's Budget tab currently conflates both — worth deciding
  whether to split "set budgets" from "track budgets" into two views or keep
  them merged, now that there's a concrete reference for the split version.

**Cross-page layout principle — fit-to-viewport, no scroll.** Every page
screenshotted so far (Net Worth, the transaction modal, the settings menu)
is composed to fit inside one screen height without vertical scrolling —
achieved via a fixed header/tab-bar zone, then exactly the cards that fit
below it, sized to the available space rather than stacking indefinitely.
This is a real structural difference from OfflineBudget's current pages,
which scroll. Worth treating as its own Phase 1 line item, not just a side
effect of density: it changes card sizing logic (cards fit available height,
not a fixed height that overflows) and may mean trimming secondary content
into a details-on-click affordance rather than a lower section of the page.

**Transaction edit modal**:
- Two-column field grid (Amount/Currency/Date on one logical row via
  label-above-input pairs, Type/Category paired, Payee/Account paired) —
  denser than a single-column form without feeling cramped.
- Description field auto-selects its full text on modal open — fast rename
  without manual select-all.
- Category and Currency fields pair a small icon/flag with the dropdown label
  (colored dot for category, country flag for currency) — consistent
  icon-left pattern reused across the whole form, not just this modal.
- Notes field carries inline helper text demonstrating its own syntax
  ("optional — use #tags to categorize", placeholder example shown), and a
  **"Split this transaction" checkbox lives inline in the same modal** rather
  than requiring a separate flow — directly relevant to OfflineBudget's
  planned category-split feature (future-work.md) as a UI placement pattern.
- Attachments is a first-class drag-and-drop zone in the same modal, not a
  separate tab.
- Footer button hierarchy: destructive (Delete, red) on the far left,
  secondary actions in the middle (Ignore, Create Rule — the latter a combo
  button with its own dropdown chevron for variants), Cancel/Save on the
  right with Save as the sole solid-indigo primary action. This
  left-destructive / right-primary spatial convention is worth adopting
  consistently across OfflineBudget's own modals if it isn't already.

### Phase 2 — Feature work, ranked by effort-to-value

8. **Household expense splitting** ("Groups" model, reimplemented independently) — highest value, no planned-work overlap, matches long-standing need for wife-visible shared reporting.
9. **Credit-card billing-cycle auto-grouping** — low effort, extends already-shipped CC tracking.
10. **Surface existing rollover fields in the Budget UI** — not new work, just exposing what's already in the schema; pull forward from future-work.md's medium-priority list. Natural to bundle with the Phase 1 category-progress-bar restyle.
11. **Investment/asset portfolio tracking** — medium effort, extends existing net worth tracking with live valuation.
12. **2FA** — auth hardening, independent of the above.

Explicitly not recommended: AI chat agent (unverified in Securo's actual product,
high effort, low fit for a single-household LAN app), Kubernetes/Helm deploy,
multi-currency, copying Securo's Cash Flow report (redundant with existing Forecast).

### License note on this whole plan

Every item above is a description of a pattern (layout, chart type, color
role, information hierarchy) to be built fresh in OfflineBudget's own React
components. None of it involves pulling Securo's source, CSS, or custom
graphics into this repo — that's the line AGPL-3.0 draws (see
[Licensing caveat](#licensing-caveat)). If a future spec pass ever wants to
reference Securo's actual component code for implementation detail, re-flag it
explicitly — that's a different, higher-scrutiny decision than what's captured
here.

## Sources

All fetched/verified live 2026-08-19 via WebFetch and curl (34 URLs across three
research passes, all HTTP 200):

- https://www.usesecuro.com/en · /pricing · /privacy
- https://github.com/securo-finance/securo (README, GitHub API metadata)
- https://docs.usesecuro.com/ — features/{dashboard,budgets,reports,agents,bank-sync,groups,workspaces,assets,recurring,goals,rules,collections,accounts,categories,net-worth,import}
- https://blog.usesecuro.com/ (15 pt-BR posts, SEO-for-Brazilian-SMB positioning)
- https://betalist.com/startups/securo
- Marketing screenshots: `screenshot-dark.png` / `screenshot-light.png` (3416×1994, directly viewed)
- Source (4th pass): `SECURITY.md`, `.env.example`, `backend/app/agents/services/crypto.py`, `backend/app/models/bank_connection.py`, `backend/app/providers/{enable_banking,simplefin,pluggy}.py`, GitHub Releases/contributors via API
