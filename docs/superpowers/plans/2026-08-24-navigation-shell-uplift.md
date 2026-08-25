# Navigation Shell Uplift Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the four navigation-shell patterns from the Securo comparison research — a month/year popover picker, an Account Detail page, an account list in the sidebar, and regrouped Settings tabs — as sub-project 1 of the OfflineBudget frontend redo.

**Architecture:** Four independent, additive frontend changes. No new backend endpoints (confirmed: `GET /accounts/{id}` and `GET /transactions?account_id=` both already exist). Each task ships a working, visually-checkable increment and commits on its own.

**Tech Stack:** React 18 + TypeScript, React Router v6, TanStack Query v5, Tailwind CSS, lucide-react icons.

**Spec:** `docs/superpowers/specs/2026-08-24-navigation-shell-uplift-design.md`

## Global Constraints

- Repo convention: commit directly to `main` after each task. No branches, no worktrees.
- No frontend test framework exists (confirmed: zero `.test.*` files, no `test` script in `package.json`). Verification per task is `npx tsc --noEmit` (must exit 0) + a manual visual check in both light and dark mode — not TDD.
- **License boundary:** every component is original OfflineBudget code written from `docs/securo-comparison.md`'s pattern descriptions. No file, CSS, or asset from `github.com/securo-finance/securo` (AGPL-3.0) may be fetched, copied, or referenced during implementation.
- Dark mode: every new `bg-`/`text-`/`border-` class must have a paired `dark:` variant, matching the convention already used throughout `Layout.tsx`/`Budget.tsx`.
- Currency formatting always goes through the existing `fmt()` helper in `frontend/src/lib/utils.ts` — never a new ad-hoc `Intl.NumberFormat` call.
- Do not modify any file under `backend/` in this plan — confirmed zero new backend work is needed.

---

### Task 1: `MonthYearPicker` component + Budget.tsx wiring

**Files:**
- Create: `frontend/src/components/MonthYearPicker.tsx`
- Modify: `frontend/src/pages/Budget.tsx:277-282` (replace the two `<select>` elements)
- Test: none (no test framework) — verify via `tsc` + manual check

**Interfaces:**
- Produces: `MonthYearPicker` component with props `{ year: number; month: number; onChange: (year: number, month: number) => void }` — a controlled component, no internal state for the selected value itself (only the popover's open/closed state and the popover's own in-progress year-stepper state are internal).

- [ ] **Step 1: Create the component**

```tsx
// frontend/src/components/MonthYearPicker.tsx
import { useState, useRef, useEffect } from "react";
import { Calendar, ChevronLeft, ChevronRight } from "lucide-react";
import { cx } from "../lib/utils";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

interface MonthYearPickerProps {
  year: number;
  month: number; // 1-12
  onChange: (year: number, month: number) => void;
}

export default function MonthYearPicker({ year, month, onChange }: MonthYearPickerProps) {
  const [open, setOpen] = useState(false);
  const [popoverYear, setPopoverYear] = useState(year);
  const rootRef = useRef<HTMLDivElement>(null);

  // Keep the popover's year stepper in sync if the caller changes `year`
  // out from under us (e.g. the arrow buttons), so re-opening the popover
  // doesn't show a stale year.
  useEffect(() => {
    setPopoverYear(year);
  }, [year]);

  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  function prevMonth() {
    if (month === 1) onChange(year - 1, 12);
    else onChange(year, month - 1);
  }

  function nextMonth() {
    if (month === 12) onChange(year + 1, 1);
    else onChange(year, month + 1);
  }

  function pickMonth(m: number) {
    onChange(popoverYear, m);
    setOpen(false);
  }

  return (
    <div ref={rootRef} className="relative flex items-center gap-1">
      <button
        onClick={prevMonth}
        className="p-1.5 rounded-full border border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700"
        aria-label="Previous month"
      >
        <ChevronLeft size={16} />
      </button>
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-full border border-gray-200 dark:border-gray-700 text-sm font-medium text-gray-900 dark:text-gray-100 hover:bg-gray-50 dark:hover:bg-gray-700"
      >
        <Calendar size={14} />
        {MONTHS[month - 1]} {year}
      </button>
      <button
        onClick={nextMonth}
        className="p-1.5 rounded-full border border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700"
        aria-label="Next month"
      >
        <ChevronRight size={16} />
      </button>

      {open && (
        <div className="absolute top-full mt-2 left-1/2 -translate-x-1/2 z-20 w-64 rounded-2xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 shadow-lg p-4">
          <div className="flex items-center justify-between mb-3">
            <button
              onClick={() => setPopoverYear(y => y - 1)}
              className="p-1 rounded-full text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700"
              aria-label="Previous year"
            >
              <ChevronLeft size={16} />
            </button>
            <span className="font-semibold text-gray-900 dark:text-gray-100">{popoverYear}</span>
            <button
              onClick={() => setPopoverYear(y => y + 1)}
              className="p-1 rounded-full text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700"
              aria-label="Next year"
            >
              <ChevronRight size={16} />
            </button>
          </div>
          <div className="grid grid-cols-4 gap-2">
            {MONTHS.map((m, i) => {
              const isSelected = popoverYear === year && i + 1 === month;
              return (
                <button
                  key={m}
                  onClick={() => pickMonth(i + 1)}
                  className={cx(
                    "py-2 rounded-lg text-sm font-medium",
                    isSelected
                      ? "bg-indigo-600 text-white"
                      : "text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700"
                  )}
                >
                  {m}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Wire it into Budget.tsx**

Replace lines 277-282 (the two `<select>` elements) in `frontend/src/pages/Budget.tsx`:

```tsx
// Before (delete these two <select> blocks):
//   <select className="input py-1 text-sm" value={month} onChange={e => setMonth(Number(e.target.value))}>
//     {MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
//   </select>
//   <select className="input py-1 text-sm w-24" value={year} onChange={e => setYear(Number(e.target.value))}>
//     {[year - 1, year, year + 1].map(y => <option key={y} value={y}>{y}</option>)}
//   </select>

// After:
<MonthYearPicker year={year} month={month} onChange={(y, m) => { setYear(y); setMonth(m); }} />
```

Add the import near the top of `Budget.tsx` (alongside the other component imports):

```tsx
import MonthYearPicker from "../components/MonthYearPicker";
```

The local `MONTHS` constant at `Budget.tsx:24` stays — it's still used elsewhere in the file (verify with `grep -n "MONTHS" frontend/src/pages/Budget.tsx` before removing anything; do not remove it as part of this task unless grep shows zero other uses).

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: exit 0

- [ ] **Step 4: Manual check**

Load `/budget` in the browser. Confirm: prev/next arrows still step the month, clicking the center pill opens the popover, the popover's year stepper works independently of the outer month, clicking a month closes the popover and updates the page. Check both light and dark mode. Click outside the popover and confirm it closes.

- [ ] **Step 5: Commit**

```bash
cd ~/Programming/Dev/OfflineBudget
git add frontend/src/components/MonthYearPicker.tsx frontend/src/pages/Budget.tsx
git commit -m "Budget: replace month/year selects with popover picker"
```

---

### Task 2: Account Detail page + route

**Files:**
- Create: `frontend/src/pages/AccountDetail.tsx`
- Modify: `frontend/src/api/index.ts` (add `accountsApi.get`)
- Modify: `frontend/src/App.tsx` (register route + import)
- Test: none — verify via `tsc` + manual check

**Interfaces:**
- Consumes: `accountsApi.list()` shape (existing, `{ id, name, type, current_balance, currency, ... }` per `backend/models.py:168-188`), `transactionsApi.list()` (existing, supports `account_id` param per `backend/routers/transactions.py:34-46`).
- Produces: `accountsApi.get(id: number): Promise<Account>` for Task 3 (sidebar) to optionally reuse; route `/accounts/:id`.

- [ ] **Step 1: Add the `get` method to `accountsApi`**

In `frontend/src/api/index.ts`, modify the existing block:

```ts
export const accountsApi = {
  list: () => api.get("/accounts").then((r) => r.data),
  get: (id: number) => api.get(`/accounts/${id}`).then((r) => r.data),
  create: (data: object) => api.post("/accounts", data).then((r) => r.data),
  update: (id: number, data: object) => api.patch(`/accounts/${id}`, data).then((r) => r.data),
  remove: (id: number) => api.delete(`/accounts/${id}`),
};
```

- [ ] **Step 2: Create the page**

```tsx
// frontend/src/pages/AccountDetail.tsx
import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { accountsApi, transactionsApi } from "../api";
import { fmt, fmtDate } from "../lib/utils";
import { ArrowLeft } from "lucide-react";

export default function AccountDetail() {
  const { id } = useParams<{ id: string }>();
  const accountId = Number(id);

  const { data: account, isLoading: accountLoading, isError: accountError } = useQuery({
    queryKey: ["account", accountId],
    queryFn: () => accountsApi.get(accountId),
    enabled: Number.isFinite(accountId),
  });

  const { data: allTransactions = [], isLoading: txnsLoading } = useQuery({
    queryKey: ["transactions", { account_id: accountId }],
    queryFn: () => transactionsApi.list({ account_id: accountId }),
    enabled: Number.isFinite(accountId),
  });
  // Backend has no `limit` param (confirmed: backend/routers/transactions.py
  // list_transactions signature) but already returns date-descending, so the
  // most recent 25 is just the first 25 of what comes back.
  const transactions = allTransactions.slice(0, 25);

  if (!Number.isFinite(accountId) || accountError) {
    return (
      <div className="space-y-4">
        <p className="text-sm text-gray-500 dark:text-gray-400">Account not found.</p>
        <Link to="/dashboard" className="text-indigo-600 dark:text-indigo-400 text-sm font-medium">
          ← Back to Dashboard
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Link to="/dashboard" className="inline-flex items-center gap-1 text-sm text-gray-500 dark:text-gray-400 hover:text-indigo-600 dark:hover:text-indigo-400">
        <ArrowLeft size={14} /> Back
      </Link>

      {accountLoading && <div className="card text-sm text-gray-400">Loading…</div>}

      {account && (
        <div className="card">
          <p className="text-xs uppercase tracking-wide text-gray-400 dark:text-gray-500">{account.type}</p>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white">{account.name}</h2>
          <p className="text-3xl font-bold text-gray-900 dark:text-white mt-2">{fmt(account.current_balance)}</p>
        </div>
      )}

      <div className="card">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-3">Recent Transactions</h3>
        {txnsLoading && <p className="text-sm text-gray-400">Loading…</p>}
        {!txnsLoading && transactions.length === 0 && (
          <p className="text-sm text-gray-400">No transactions for this account yet.</p>
        )}
        {!txnsLoading && transactions.length > 0 && (
          <ul className="divide-y divide-gray-100 dark:divide-gray-700">
            {transactions.map((t: any) => (
              <li key={t.id} className="py-2 flex items-center justify-between text-sm">
                <div className="min-w-0">
                  <p className="text-gray-900 dark:text-gray-100 truncate">{t.description}</p>
                  <p className="text-xs text-gray-400 dark:text-gray-500">{fmtDate(t.date)}</p>
                </div>
                <span className={`font-semibold tabular-nums shrink-0 ml-3 ${parseFloat(t.amount) >= 0 ? "text-green-600" : "text-red-600"}`}>
                  {parseFloat(t.amount) >= 0 ? "+" : ""}{fmt(t.amount)}
                </span>
              </li>
            ))}
          </ul>
        )}
        <Link to="/transactions" className="inline-block mt-3 text-sm text-indigo-600 dark:text-indigo-400 font-medium">
          View all in Transactions →
        </Link>
      </div>
    </div>
  );
}
```

This is a deliberately independent, read-only row rendering — NOT a reuse of `Transactions.tsx`'s table rows. Those rows are tightly coupled to page-level inline-edit state (`editingNotesId`, `editingCatId`, `handleCatChange`, `catMap`, `accountMap`) and a `CategoryCell` sub-component (confirmed by reading `Transactions.tsx:555-600` during planning). Extracting that into a shared component would be a much larger, riskier refactor than this task justifies, and a read-only preview list is the right shape for a detail page anyway — an editable list belongs on the Transactions page. Do not attempt the extraction as part of this task.

- [ ] **Step 3: Register the route**

In `frontend/src/App.tsx`, add the import near the other page imports:

```tsx
import AccountDetail from "./pages/AccountDetail";
```

Add the route inside the `<Route path="/" ...>` block, alongside the other nested routes (order doesn't matter functionally, but group it near `transactions`/`budget` for readability):

```tsx
<Route path="accounts/:id" element={<AccountDetail />} />
```

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: exit 0

- [ ] **Step 5: Manual check**

Navigate directly to `/accounts/1` (or whatever a real account id is in your data) and confirm the header balance and recent transactions render. Navigate to `/accounts/999999` (nonexistent) and confirm the not-found state renders instead of a blank page or a thrown error. Check both light and dark mode.

- [ ] **Step 6: Commit**

```bash
cd ~/Programming/Dev/OfflineBudget
git add frontend/src/pages/AccountDetail.tsx frontend/src/api/index.ts frontend/src/App.tsx
git commit -m "Add Account Detail page at /accounts/:id"
```

---

### Task 3: Account list in the sidebar

**Files:**
- Modify: `frontend/src/components/Layout.tsx`

**Interfaces:**
- Consumes: the `accounts` query already fetched in `Layout.tsx:14-18` (`useQuery({ queryKey: ["accounts"], queryFn: accountsApi.list, staleTime: 30_000 })`) — no new query needed. Route `/accounts/:id` from Task 2.

- [ ] **Step 1: Add sidebar state and render block**

In `frontend/src/components/Layout.tsx`, add a new piece of state near the existing `pinned` state (around line 20):

```tsx
const [accountsExpanded, setAccountsExpanded] = useState(false);
```

Just above the `return (` statement, derive a sorted list from the existing `accounts` query result. `accountsApi.list()` returns accounts in DB insertion order (confirmed: `backend/routers/accounts.py`'s `list_accounts` has no `order_by`), so sort client-side:

```tsx
const sortedAccounts = [...(accounts as any[])].sort(
  (a, b) => a.type.localeCompare(b.type) || a.name.localeCompare(b.name)
);
```

Add this block inside the `<aside>`, between the closing `</nav>` and the `<div className="px-3 py-3 border-t ...">` sign-out block (i.e. as a new sidebar section above sign-out, matching the reference pattern's sidebar-footer placement). Every reference below uses `sortedAccounts`, never the raw `accounts` query result:

```tsx
{sortedAccounts.length > 0 && (
  <div className="px-3 py-3 border-t border-gray-200 dark:border-gray-700">
    <p className="px-2 pb-1 text-[11px] font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-400">
      Accounts
    </p>
    <ul className="space-y-0.5">
      {(accountsExpanded ? sortedAccounts : sortedAccounts.slice(0, 4)).map((a: any) => (
        <li key={a.id}>
          <NavLink
            to={`/accounts/${a.id}`}
            className={({ isActive }) =>
              cx(
                "flex items-center justify-between px-2 py-1.5 rounded-lg text-sm",
                isActive ? "bg-indigo-50 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-300" : "text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700/50"
              )
            }
          >
            <span className="truncate">{a.name}</span>
            <span className={`shrink-0 ml-2 tabular-nums ${parseFloat(a.current_balance) < 0 ? "text-red-500 dark:text-red-400" : "text-gray-500 dark:text-gray-400"}`}>
              {fmt(a.current_balance)}
            </span>
          </NavLink>
        </li>
      ))}
    </ul>
    {sortedAccounts.length > 4 && (
      <button
        onClick={() => setAccountsExpanded(e => !e)}
        className="mt-1 px-2 text-xs font-medium text-indigo-600 dark:text-indigo-400"
      >
        {accountsExpanded ? "Show less" : `+${sortedAccounts.length - 4} more`}
      </button>
    )}
  </div>
)}
```

Add the `fmt` import to `Layout.tsx`'s existing `../lib/utils` import line (it already imports `cx` from there — extend that line rather than adding a new import):

```tsx
import { cx, fmt } from "../lib/utils";
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: exit 0

- [ ] **Step 3: Manual check**

Confirm the sidebar shows an "Accounts" section with name + balance per account, capped at 4 with a working "+N more" toggle when you have more than 4 accounts (if your data has ≤4, temporarily lower the slice count to 2 to verify the overflow control, then revert). Click an account row and confirm it navigates to `/accounts/:id` and highlights as active. Check both light and dark mode.

- [ ] **Step 4: Commit**

```bash
cd ~/Programming/Dev/OfflineBudget
git add frontend/src/components/Layout.tsx
git commit -m "Layout: add account balances list to sidebar"
```

---

### Task 4: Regrouped Settings tabs

**Files:**
- Modify: `frontend/src/pages/Settings.tsx`

**Interfaces:** none — purely presentational, no new routes, no new data.

- [ ] **Step 1: Restructure the `TABS` array into grouped sections**

Replace the flat `TABS` array in `frontend/src/pages/Settings.tsx` (currently lines 15-25) with a grouped structure:

```tsx
const TAB_GROUPS = [
  {
    label: "Profile",
    items: [
      { to: "/settings/profile", label: "Profile & Security", icon: User },
      { to: "/settings/preferences", label: "Preferences", icon: SlidersHorizontal },
      { to: "/settings/notifications", label: "Notifications & Email", icon: Bell },
    ],
  },
  {
    label: "Money",
    items: [
      { to: "/settings/accounts", label: "Accounts & Bank Sync", icon: Link },
      { to: "/settings/categories", label: "Categories & Rules", icon: Tags },
      { to: "/settings/tax", label: "Tax", icon: Receipt },
      { to: "/settings/household", label: "Household", icon: UsersIcon },
    ],
  },
  {
    label: "Data & Trust",
    items: [
      { to: "/settings/verification", label: "Verification Feedback", icon: Flag },
    ],
  },
  {
    label: "Danger Zone",
    items: [
      { to: "/settings/danger", label: "Danger Zone", icon: AlertTriangle, danger: true },
    ],
  },
];
```

Replace the `<nav>` block's rendering (currently a flat `.map` over `TABS`) with a grouped render:

```tsx
<nav className="md:w-48 shrink-0 flex md:flex-col gap-1 overflow-x-auto">
  {TAB_GROUPS.map((group, gi) => (
    <div key={group.label} className={cx("flex md:flex-col gap-1", gi > 0 && "md:mt-3 md:pt-3 md:border-t md:border-gray-100 dark:md:border-gray-700")}>
      <p className="hidden md:block px-3 pb-1 text-[11px] font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">
        {group.label}
      </p>
      {group.items.map(t => (
        <NavLink
          key={t.to}
          to={t.to}
          className={({ isActive }) =>
            cx(
              "flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium whitespace-nowrap",
              t.danger
                ? (isActive ? "bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-400" : "text-red-500 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20")
                : (isActive
                    ? "bg-indigo-50 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-300"
                    : "text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700/50")
            )
          }
        >
          <t.icon size={16} />
          {t.label}
        </NavLink>
      ))}
    </div>
  ))}
</nav>
```

Note the mobile layout (`flex` without `md:flex-col`) stays a horizontal scroll of all tabs ungrouped on small screens — the group label `<p>` is `hidden md:block` so mobile doesn't show four tiny section headers in a horizontally-scrolling strip, but every tab is still present and reachable. Don't change the `<Routes>` block below the nav — routes are unaffected by this grouping.

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: exit 0

- [ ] **Step 3: Manual check**

Load `/settings` and confirm four labeled groups render with dividers between them on desktop width, all nine tabs are still reachable, active-tab highlighting still works, and the Danger Zone tab still renders red. Resize to mobile width and confirm the tab strip still scrolls horizontally with every tab present (group labels may disappear at that width — that's expected). Check both light and dark mode.

- [ ] **Step 4: Commit**

```bash
cd ~/Programming/Dev/OfflineBudget
git add frontend/src/pages/Settings.tsx
git commit -m "Settings: group tabs by Profile/Money/Data & Trust/Danger Zone"
```

---

## Final Verification

After all four tasks are committed:

- [ ] Run `cd frontend && npx tsc --noEmit` one more time from a clean state — exit 0
- [ ] Run `git log --oneline -4` and confirm all four commits are present on `main`, unpushed (per repo convention, Dan reviews before push)
- [ ] Run `git diff --name-only main~4 main -- backend/` and confirm it returns nothing — zero backend files touched anywhere in this plan
- [ ] Manual pass through all four features together in one browser session, both light and dark mode, before handing back to Dan for his pre-push review
