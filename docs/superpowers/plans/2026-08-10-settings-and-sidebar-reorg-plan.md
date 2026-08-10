# Settings & Sidebar Reorganization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat 12-item sidebar with a pinned-favorites row (Dashboard always pinned) above 3 fixed groups, and split the 1439-line `Settings.tsx` into 7 tabbed sub-pages, each its own file.

**Architecture:** Sidebar nav metadata and the `pinnedNav` localStorage model move into a new shared `frontend/src/lib/navItems.ts`, imported by `Layout.tsx` (renders it) and the new Preferences tab (lets the user edit it). `Settings.tsx` becomes a thin shell rendering a tab sub-nav plus nested react-router routes; each tab's state/queries/mutations/JSX move into their own file under a new `frontend/src/pages/settings/` directory, moved verbatim from the current `Settings.tsx` (same logic, same behavior, new location) unless a step explicitly says otherwise.

**Tech Stack:** React + TypeScript + react-router v6 + @tanstack/react-query, Vite. No backend changes, no new API endpoints — `pinnedNav` is client-side `localStorage`, same as today's `navOrder`. No frontend test framework exists in this repo — verification is `tsc -b` (frontend/) plus manual/visual checks, matching how every prior frontend task in this project has been verified.

## Global Constraints

- **Sidebar structure:** pinned row (Dashboard, permanently pinned + user's picks) → Overview (Net Worth, Calendar) → Money (Transactions, Spending, Recurring, Import) → Planning (Budget, Goals, Credit Cards, Forecast) → Settings (always last, ungrouped). An item pinned by the user is removed from its group's list (no duplication).
- **Favorites are Settings-page checkbox toggles**, not drag-and-drop. This plan deletes the existing drag-to-reorder sidebar (`navOrder` localStorage key, up/down arrow buttons, `moveNav`/`resetNavOrder`) entirely and replaces it with `pinnedNav` (a `string[]` of pinned `to` paths, Dashboard implicit/not stored).
- **Migration:** on first load, if `localStorage.pinnedNav` doesn't exist and `localStorage.navOrder` does, seed `pinnedNav` from `navOrder`'s first 4 pinnable (non-Dashboard, non-Settings) entries, then delete `navOrder` so migration never re-runs.
- **Settings tabs and routes** (`/settings/:tab`, default redirects to `/settings/profile`):
  | Route | Tab label | Contents (moved from today's Settings.tsx sections) |
  |---|---|---|
  | `profile` | Profile & Security | Profile, Email Notifications, Recovery Code, Change Password |
  | `preferences` | Preferences | Dark Mode, Setup Wizard, **new** Pinned Sidebar Items picker, Suggested Transfer Increment |
  | `accounts` | Accounts & Bank Sync | Accounts, Bank Connections |
  | `categories` | Categories & Rules | Categories, Transaction Rules |
  | `tax` | Tax | Tax Profile, Social Security Tracker |
  | `household` | Household | Users, Activity Log (both admin-only, same as today) |
  | `danger` | Danger Zone | Danger Zone (red accent kept, still last) |
- **Deep-link updates:** `Dashboard.tsx`'s "Add Account" button → `/settings/accounts`; `Spending.tsx`'s tax-estimate error link → `/settings/tax`.
- **This refactor is not independently shippable mid-plan.** Tasks 3-9 each move one section out of the shrinking legacy `Settings.tsx` into its own tab file. Between those tasks, sections not yet moved are temporarily absent from the rendered `/settings` page (they're still in the legacy file, just not wired into the new shell's router yet, per Task 2's setup). This is expected — call it out in task-scoped review, don't treat it as a regression. The page is complete again after Task 9.
- **tsc baseline drift is expected and intentional.** The current 13-error baseline includes two bugs that live inside `Settings.tsx` today: an unused `HelpPanel` import (`Settings.tsx:11`) and a type error in `openNewCat` (`Settings.tsx:143`, an object literal missing the `tax_deductible` field `catForm`'s type requires). Both disappear in Task 2, the moment the old monolithic file is replaced wholesale by the new thin shell (not fixed in place — the code containing them stops existing) — dropping the baseline from 13 to 11. Task 6, which re-creates the Categories logic in its new home, writes `openNewCat` correctly from the start so the bug is never reintroduced. Every task from Task 2 onward expects `11`, not `13` — each task below states its own expected count explicitly.
- **Verification is `tsc -b` + manual checks, not Interceptor**, despite the design spec mentioning Interceptor visual verification as part of testing. This repo has no pinned Interceptor test profile configured (a one-time setup step still pending from earlier in this project's history) — every prior frontend task in this codebase has used `tsc -b` plus a described manual pass instead, and this plan follows that same established practice. If Interceptor becomes available before this plan executes, layering it on top of each task's manual-verification step is a reasonable enhancement, but it's not required to consider this plan's tasks complete.

---

### Task 1: Shared nav metadata + pinned-favorites sidebar

**Files:**
- Create: `frontend/src/lib/navItems.ts`
- Modify: `frontend/src/components/Layout.tsx` (full rewrite of the `nav`/`loadOrderedNav` section and the sidebar/mobile-nav JSX)

**Interfaces:**
- Consumes: nothing new (existing `cx` from `../lib/utils`).
- Produces: `NAV_GROUPS`, `PINNABLE_ITEMS`, `DASHBOARD_ITEM`, `SETTINGS_ITEM`, `PINNED_STORAGE_KEY`, `loadPinnedNav(): string[]` from `frontend/src/lib/navItems.ts` — Task 4 (Preferences tab) imports `PINNABLE_ITEMS`, `loadPinnedNav`, `PINNED_STORAGE_KEY` from here to build the pin/unpin picker.

This is a self-contained sidebar rewrite — no dependency on the Settings split, safe to do first.

- [ ] **Step 1: Create the shared nav metadata module**

```ts
// frontend/src/lib/navItems.ts
import {
  LayoutDashboard, CreditCard, TrendingUp, PieChart,
  Repeat, ArrowLeftRight, Target, Settings, Upload,
  CalendarDays, Wallet, BarChart2, LucideIcon,
} from "lucide-react";

export interface NavItem {
  to: string;
  icon: LucideIcon;
  label: string;
}

export const DASHBOARD_ITEM: NavItem = { to: "/dashboard", icon: LayoutDashboard, label: "Dashboard" };
export const SETTINGS_ITEM: NavItem = { to: "/settings", icon: Settings, label: "Settings" };

export interface NavGroup {
  key: "overview" | "money" | "planning";
  label: string;
  items: NavItem[];
}

export const NAV_GROUPS: NavGroup[] = [
  {
    key: "overview", label: "Overview", items: [
      { to: "/net-worth", icon: BarChart2, label: "Net Worth" },
      { to: "/calendar", icon: CalendarDays, label: "Calendar" },
    ],
  },
  {
    key: "money", label: "Money", items: [
      { to: "/transactions", icon: ArrowLeftRight, label: "Transactions" },
      { to: "/spending", icon: PieChart, label: "Spending" },
      { to: "/recurring", icon: Repeat, label: "Recurring" },
      { to: "/import", icon: Upload, label: "Import" },
    ],
  },
  {
    key: "planning", label: "Planning", items: [
      { to: "/budget", icon: Target, label: "Budget" },
      { to: "/goals", icon: Wallet, label: "Goals" },
      { to: "/credit-cards", icon: CreditCard, label: "Credit Cards" },
      { to: "/forecast", icon: TrendingUp, label: "Forecast" },
    ],
  },
];

// Every item that CAN be pinned -- everything except Dashboard (always
// pinned, not a user choice) and Settings (always renders separately at
// the bottom of the sidebar, never grouped or pinnable).
export const PINNABLE_ITEMS: NavItem[] = NAV_GROUPS.flatMap(g => g.items);

export const PINNED_STORAGE_KEY = "pinnedNav";
const LEGACY_ORDER_STORAGE_KEY = "navOrder";

/** Reads the user's pinned nav items (`to` paths, Dashboard excluded --
 * it's always pinned and never stored). One-time migration: if the old
 * drag-order key still exists and the new key doesn't, seed pinnedNav from
 * its first 4 pinnable entries and delete the old key so this never runs
 * twice. */
export function loadPinnedNav(): string[] {
  try {
    const saved = localStorage.getItem(PINNED_STORAGE_KEY);
    if (saved) return JSON.parse(saved);
  } catch { /* fall through to migration/default */ }

  try {
    const legacy = localStorage.getItem(LEGACY_ORDER_STORAGE_KEY);
    if (legacy) {
      const order = JSON.parse(legacy) as string[];
      const pinnable = new Set(PINNABLE_ITEMS.map(i => i.to));
      const migrated = order.filter(to => pinnable.has(to)).slice(0, 4);
      localStorage.setItem(PINNED_STORAGE_KEY, JSON.stringify(migrated));
      localStorage.removeItem(LEGACY_ORDER_STORAGE_KEY);
      return migrated;
    }
  } catch { /* fall through to empty default */ }

  return [];
}
```

- [ ] **Step 2: Run tsc to confirm the new file compiles standalone**

Run: `cd frontend && npx tsc -b 2>&1 | grep -c "error TS"`
Expected: `13` (unchanged — this file isn't imported anywhere yet, and introduces no errors of its own).

- [ ] **Step 3: Rewrite Layout.tsx to use the shared module and render pinned + grouped sections**

Replace the ENTIRE current content of `frontend/src/components/Layout.tsx` with:

```tsx
import { useState, useEffect } from "react";
import { Outlet, NavLink, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { clearAuth, getUser } from "../store/auth";
import { authApi, accountsApi } from "../api";
import QuickStartWizard from "./QuickStartWizard";
import { LogOut } from "lucide-react";
import { cx } from "../lib/utils";
import { DASHBOARD_ITEM, SETTINGS_ITEM, NAV_GROUPS, loadPinnedNav, PINNABLE_ITEMS } from "../lib/navItems";

export default function Layout() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const user = getUser();
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: authApi.me, staleTime: 60_000 });
  const { data: accounts = [], isSuccess: accountsLoaded } = useQuery({
    queryKey: ["accounts"],
    queryFn: accountsApi.list,
    staleTime: 30_000,
  });
  const [wizardOpen, setWizardOpen] = useState(false);
  const [pinned, setPinned] = useState<string[]>(loadPinnedNav);

  // Latch open once on first load if no accounts exist — don't re-derive from live query
  // so the wizard stays visible after step 1 creates the first account.
  useEffect(() => {
    if (accountsLoaded && (accounts as any[]).length === 0) {
      setWizardOpen(true);
    }
  }, [accountsLoaded]); // eslint-disable-line react-hooks/exhaustive-deps

  // Allow Settings (or any page) to open the wizard via a custom event.
  useEffect(() => {
    const handler = () => setWizardOpen(true);
    window.addEventListener("open-wizard", handler);
    return () => window.removeEventListener("open-wizard", handler);
  }, []);

  useEffect(() => {
    const handler = () => setPinned(loadPinnedNav());
    window.addEventListener("nav-order-changed", handler);
    return () => window.removeEventListener("nav-order-changed", handler);
  }, []);

  const showWizard = wizardOpen;
  const pinnedSet = new Set(pinned);
  const pinnedItems = pinned.map(to => PINNABLE_ITEMS.find(i => i.to === to)).filter((i): i is typeof PINNABLE_ITEMS[number] => !!i);
  const mobileItems = [DASHBOARD_ITEM, ...pinnedItems].slice(0, 5);

  function logout() {
    clearAuth();
    navigate("/login");
  }

  function navLinkClass({ isActive }: { isActive: boolean }) {
    return cx(isActive ? "nav-link-active" : "nav-link");
  }

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside className="hidden md:flex w-60 flex-col bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700 shrink-0">
        <div className="px-5 py-4 border-b border-gray-200 dark:border-gray-700">
          <h1 className="text-lg font-bold text-indigo-600">OfflineBudget</h1>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{me?.display_name ?? user?.display_name}</p>
        </div>
        <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
          <NavLink to={DASHBOARD_ITEM.to} className={navLinkClass}>
            <DASHBOARD_ITEM.icon size={18} />
            {DASHBOARD_ITEM.label}
          </NavLink>
          {pinnedItems.map(item => (
            <NavLink key={item.to} to={item.to} className={navLinkClass}>
              <item.icon size={18} />
              {item.label}
            </NavLink>
          ))}
          {pinnedItems.length > 0 && <div className="my-2 border-t border-gray-100 dark:border-gray-700" />}
          {NAV_GROUPS.map(group => {
            const visible = group.items.filter(i => !pinnedSet.has(i.to));
            if (visible.length === 0) return null;
            return (
              <div key={group.key} className="pt-3 first:pt-0">
                <p className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">{group.label}</p>
                {visible.map(item => (
                  <NavLink key={item.to} to={item.to} className={navLinkClass}>
                    <item.icon size={18} />
                    {item.label}
                  </NavLink>
                ))}
              </div>
            );
          })}
          <div className="my-2 border-t border-gray-100 dark:border-gray-700" />
          <NavLink to={SETTINGS_ITEM.to} className={navLinkClass}>
            <SETTINGS_ITEM.icon size={18} />
            {SETTINGS_ITEM.label}
          </NavLink>
        </nav>
        <div className="px-3 py-3 border-t border-gray-200 dark:border-gray-700">
          <button onClick={logout} className="nav-link w-full text-red-600 hover:bg-red-50 hover:text-red-700">
            <LogOut size={18} />
            Sign out
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto bg-gray-50 dark:bg-gray-900">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-6">
          <Outlet />
        </div>
      </main>

      {showWizard && (
        <QuickStartWizard
          onComplete={() => {
            qc.invalidateQueries({ queryKey: ["accounts"] });
            setWizardOpen(false);
          }}
          onDismiss={() => setWizardOpen(false)}
        />
      )}

      {/* Mobile bottom nav */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 bg-white dark:bg-gray-800 border-t border-gray-200 dark:border-gray-700 flex justify-around px-2 py-2 z-50">
        {mobileItems.map(item => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              cx("flex flex-col items-center gap-0.5 px-2 py-1 rounded-lg text-xs font-medium",
                isActive ? "text-indigo-600" : "text-gray-500")
            }
          >
            <item.icon size={20} />
            <span>{item.label.split(" ")[0]}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
```

- [ ] **Step 4: Run tsc to verify**

Run: `cd frontend && npx tsc -b 2>&1 | grep -c "error TS"`
Expected: `13` (unchanged — Layout.tsx had no pre-existing errors, and this rewrite introduces none).

- [ ] **Step 5: Manual verification**

Start the dev server (`cd frontend && npm run dev` or however this project is normally run locally) and open the app in a browser:
- Sidebar shows Dashboard first, then (initially, before any migration/pinning) no pinned row, then Overview/Money/Planning groups, then Settings last.
- If `localStorage.navOrder` exists from before this change, reload once and confirm `localStorage.pinnedNav` now exists and `navOrder` is gone (check via browser devtools → Application → Local Storage).
- Mobile width (resize below `md` breakpoint, ~768px): bottom nav shows Dashboard + up to 4 pinned items.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/navItems.ts frontend/src/components/Layout.tsx
git commit -m "Replace drag-to-reorder sidebar with pinned-favorites + grouped sections

Dashboard is now permanently pinned; other items become favorites via
a Settings toggle (added in a later task), not dragging. Sidebar renders
a pinned row, then Overview/Money/Planning groups (pinned items removed
from their group to avoid duplication), then Settings last. One-time
migration seeds pinnedNav from the old navOrder's first 4 entries."
```

---

### Task 2: Settings shell + routing skeleton + Profile & Security tab

**Files:**
- Modify: `frontend/src/App.tsx:51` (route path)
- Create: `frontend/src/pages/settings/ProfileTab.tsx`
- Rewrite: `frontend/src/pages/Settings.tsx` (becomes the thin shell)

**Interfaces:**
- Consumes: `authApi` from `../../api` (same API client already used).
- Produces: the tab-shell pattern every later task (3-8) follows — a `TABS` array in `Settings.tsx` each task appends one entry to, and a matching `<Route path="..." element={<...Tab />} />` each task adds.

This is the first tab extraction — it establishes the pattern. Read `docs/superpowers/specs/2026-08-10-settings-and-sidebar-reorg-design.md` if anything below is unclear about *why* a piece is organized this way; this task's *what* is fully specified below.

- [ ] **Step 1: Widen the Settings route to accept sub-paths**

In `frontend/src/App.tsx`, change:
```tsx
<Route path="settings" element={<Settings />} />
```
to:
```tsx
<Route path="settings/*" element={<Settings />} />
```
(The trailing `/*` lets `Settings`'s own nested `<Routes>` — added in Step 3 below — consume `/settings/profile`, `/settings/accounts`, etc.)

- [ ] **Step 2: Create the Profile & Security tab**

Move ONLY the Profile-related state/mutations/JSX out of the current `frontend/src/pages/Settings.tsx` (Profile display name, Email Notifications, Recovery Code, Change Password — NOT Tax Profile or Social Security, those move to the `tax` tab in Task 6). This is the exact content currently at `Settings.tsx` lines 160-182 (Profile/recovery state), 202-244 (the `me`-driven effect subset covering just `profileName`/`profileEmail`, `updateMeMut`, `sendTestEmailMut`, `changePasswordMut`, `submitPassword` — NOT the tax-profile fields in that same effect, those stay behind for Task 6 to move), and the JSX at lines 835-1084 up through the closing `</div>}\n      </div>` of the Profile card (stop before `{/* ── Danger Zone ── */}`), plus the Recovery Code modal already inside that block (lines 904-952).

```tsx
// frontend/src/pages/settings/ProfileTab.tsx
import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { authApi } from "../../api";
import { User, Mail, KeyRound } from "lucide-react";

export default function ProfileTab() {
  const qc = useQueryClient();
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: authApi.me });
  const [profileName, setProfileName] = useState("");
  const [profileSaved, setProfileSaved] = useState(false);
  const [pwForm, setPwForm] = useState({ current: "", next: "", confirm: "" });
  const [pwError, setPwError] = useState<string | null>(null);
  const [pwSaved, setPwSaved] = useState(false);
  const [profileEmail, setProfileEmail] = useState("");
  const [testEmailStatus, setTestEmailStatus] = useState<"idle" | "sending" | "ok" | "err">("idle");
  const [recoveryCode, setRecoveryCode] = useState<string | null>(null);
  const [recoveryCodeStatus, setRecoveryCodeStatus] = useState<"idle" | "generating" | "ok" | "err">("idle");
  const [recoveryCodeCopied, setRecoveryCodeCopied] = useState(false);
  const [recoveryCodeCopyError, setRecoveryCodeCopyError] = useState(false);
  const generateRecoveryCodeMut = useMutation({
    mutationFn: authApi.generateRecoveryCode,
    onMutate: () => setRecoveryCodeStatus("generating"),
    onSuccess: (data) => {
      setRecoveryCode(data.code);
      setRecoveryCodeStatus("ok");
      qc.invalidateQueries({ queryKey: ["me"] });
    },
    onError: () => { setRecoveryCodeStatus("err"); setTimeout(() => setRecoveryCodeStatus("idle"), 3000); },
  });

  React.useEffect(() => {
    if (me) {
      setProfileName(me.display_name ?? "");
      setProfileEmail(me.email ?? "");
    }
  }, [me]);
  const updateMeMut = useMutation({
    mutationFn: authApi.updateMe,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["me"] }); setProfileSaved(true); setTimeout(() => setProfileSaved(false), 2000); },
  });
  const sendTestEmailMut = useMutation({
    mutationFn: authApi.sendTestEmail,
    onMutate: () => setTestEmailStatus("sending"),
    onSuccess: () => { setTestEmailStatus("ok"); setTimeout(() => setTestEmailStatus("idle"), 3000); },
    onError: () => { setTestEmailStatus("err"); setTimeout(() => setTestEmailStatus("idle"), 3000); },
  });
  const changePasswordMut = useMutation({
    mutationFn: authApi.changePassword,
    onSuccess: () => { setPwForm({ current: "", next: "", confirm: "" }); setPwError(null); setPwSaved(true); setTimeout(() => setPwSaved(false), 2000); },
    onError: (e: any) => setPwError(e?.response?.data?.detail ?? "Failed to change password"),
  });
  function submitPassword(e: React.FormEvent) {
    e.preventDefault();
    if (pwForm.next !== pwForm.confirm) { setPwError("New passwords don't match"); return; }
    if (pwForm.next.length < 6) { setPwError("Password must be at least 6 characters"); return; }
    setPwError(null);
    changePasswordMut.mutate({ current_password: pwForm.current, new_password: pwForm.next });
  }

  return (
    <div className="card">
      <h3 className="font-semibold text-gray-900 dark:text-gray-100 flex items-center gap-2 mb-4"><User size={16} className="text-indigo-500" /> Profile</h3>
      <div className="space-y-5">
        <div className="flex items-end gap-3">
          <div className="flex-1 max-w-xs">
            <label className="label">Display Name</label>
            <input className="input" value={profileName} onChange={e => setProfileName(e.target.value)} placeholder="Your name" />
          </div>
          <button
            onClick={() => updateMeMut.mutate({ display_name: profileName })}
            disabled={updateMeMut.isPending || !profileName.trim()}
            className="btn-primary text-sm"
          >
            {updateMeMut.isPending ? "Saving…" : "Save"}
          </button>
          {profileSaved && <span className="text-sm text-green-600">Saved!</span>}
        </div>
        <div className="space-y-2">
          <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300 flex items-center gap-2"><Mail size={14} /> Email Notifications</h4>
          <p className="text-xs text-gray-500 dark:text-gray-400">Used for daily summary emails. Requires SMTP to be configured on the server. Enter multiple addresses separated by commas to send to more than one person.</p>
          <div className="flex items-end gap-3">
            <div className="flex-1 max-w-xs">
              <label className="label">Email Address(es)</label>
              <input type="email" multiple className="input" value={profileEmail} onChange={e => setProfileEmail(e.target.value)} placeholder="you@example.com, spouse@example.com" />
            </div>
            <button
              onClick={() => updateMeMut.mutate({ email: profileEmail || null })}
              disabled={updateMeMut.isPending}
              className="btn-primary text-sm"
            >
              Save
            </button>
            <button
              onClick={() => sendTestEmailMut.mutate()}
              disabled={sendTestEmailMut.isPending || !me?.email}
              className="btn-secondary text-sm"
              title={!me?.email ? "Save an email address first" : "Send a test email"}
            >
              {testEmailStatus === "sending" ? "Sending…" : testEmailStatus === "ok" ? "Sent!" : testEmailStatus === "err" ? "Failed" : "Test"}
            </button>
          </div>
        </div>
        <div className="pt-2 border-t">
          <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
            A recovery code lets you reset your password without email. Generating a new one
            replaces any existing code.
          </p>
          <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
            {me?.recovery_code_created_at
              ? `Recovery code generated on ${new Date(me.recovery_code_created_at).toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric" })}`
              : "No recovery code set"}
          </p>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => generateRecoveryCodeMut.mutate()}
            disabled={generateRecoveryCodeMut.isPending}
          >
            {recoveryCodeStatus === "generating" ? "Generating…" : "Generate Recovery Code"}
          </button>
          {recoveryCodeStatus === "err" && (
            <span className="ml-2 text-sm text-red-600">Failed to generate a recovery code. Try again.</span>
          )}
        </div>

        {recoveryCode && (
          <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4">
            <div className="card max-w-sm w-full space-y-4">
              <h3 className="font-semibold text-gray-900">Save Your Recovery Code</h3>
              <p className="text-sm text-gray-500">
                This won't be shown again. Store it somewhere safe — it's the only way to reset
                your password without email.
              </p>
              <code className="block text-center text-lg font-mono bg-gray-100 rounded-lg py-3 tracking-wider">
                {recoveryCode}
              </code>
              <button
                type="button"
                className="btn-primary w-full"
                onClick={async () => {
                  try {
                    if (!navigator.clipboard) throw new Error("Clipboard API unavailable");
                    await navigator.clipboard.writeText(recoveryCode);
                    setRecoveryCodeCopied(true);
                    setRecoveryCodeCopyError(false);
                    setTimeout(() => setRecoveryCodeCopied(false), 2000);
                  } catch {
                    setRecoveryCodeCopied(false);
                    setRecoveryCodeCopyError(true);
                  }
                }}
              >
                {recoveryCodeCopied ? "Copied!" : "Copy to Clipboard"}
              </button>
              {recoveryCodeCopyError && (
                <p className="text-sm text-red-600 text-center -mt-2">
                  Couldn't copy automatically — select the code above and copy it manually.
                </p>
              )}
              <button
                type="button"
                className="text-sm text-gray-500 w-full text-center"
                onClick={() => {
                  setRecoveryCode(null);
                  setRecoveryCodeCopied(false);
                  setRecoveryCodeCopyError(false);
                  setRecoveryCodeStatus("idle");
                }}
              >
                I've saved it — close
              </button>
            </div>
          </div>
        )}

        <form onSubmit={submitPassword} className="space-y-3 border-t border-gray-100 dark:border-gray-700 pt-4">
          <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300 flex items-center gap-2"><KeyRound size={14} /> Change Password</h4>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 max-w-xl">
            <div>
              <label className="label">Current Password</label>
              <input type="password" className="input" value={pwForm.current} onChange={e => setPwForm({ ...pwForm, current: e.target.value })} required />
            </div>
            <div>
              <label className="label">New Password</label>
              <input type="password" className="input" value={pwForm.next} onChange={e => setPwForm({ ...pwForm, next: e.target.value })} required />
            </div>
            <div>
              <label className="label">Confirm New Password</label>
              <input type="password" className="input" value={pwForm.confirm} onChange={e => setPwForm({ ...pwForm, confirm: e.target.value })} required />
            </div>
          </div>
          {pwError && <p className="text-sm text-red-600">{pwError}</p>}
          {pwSaved && <p className="text-sm text-green-600">Password changed!</p>}
          <button type="submit" disabled={changePasswordMut.isPending} className="btn-primary text-sm">
            {changePasswordMut.isPending ? "Updating…" : "Update Password"}
          </button>
        </form>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Replace `Settings.tsx` with the thin shell, routing only to Profile so far**

The DELETE side of this step: nothing to delete yet from the OLD file's on-disk content in this step's diff, because this step REPLACES the whole file. The sections not yet extracted (Preferences, Accounts, Bank Connections, Categories, Rules, Users, Activity Log, Tax, Danger Zone) are temporarily gone from the rendered page — Tasks 3-8 bring each back into its own tab, one at a time. This is expected (see Global Constraints).

```tsx
// frontend/src/pages/Settings.tsx
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { User } from "lucide-react";
import { cx } from "../lib/utils";
import ProfileTab from "./settings/ProfileTab";

const TABS = [
  { to: "profile", label: "Profile & Security", icon: User },
];

export default function Settings() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-gray-100">Settings</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400">Manage accounts, categories, and preferences</p>
      </div>
      <div className="flex flex-col md:flex-row gap-6">
        <nav className="md:w-48 shrink-0 flex md:flex-col gap-1 overflow-x-auto">
          {TABS.map(t => (
            <NavLink
              key={t.to}
              to={t.to}
              className={({ isActive }) =>
                cx(
                  "flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium whitespace-nowrap",
                  isActive
                    ? "bg-indigo-50 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400"
                    : "text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700/50"
                )
              }
            >
              <t.icon size={16} />
              {t.label}
            </NavLink>
          ))}
        </nav>
        <div className="flex-1 min-w-0">
          <Routes>
            <Route index element={<Navigate to="profile" replace />} />
            <Route path="profile" element={<ProfileTab />} />
          </Routes>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run tsc to verify**

Run: `cd frontend && npx tsc -b 2>&1 | grep -c "error TS"`
Expected: `11`. Step 3 replaced the entire old `Settings.tsx` rather than trimming it, so both errors that lived in that file (the unused `HelpPanel` import and `openNewCat`'s type error, see Global Constraints) are gone the moment the old content stops existing — not because their specific code was fixed, but because that code no longer exists anywhere. If you still see `13`, re-check that Step 3 fully replaced the file's content rather than partially editing it.

- [ ] **Step 5: Manual verification**

With the dev server running, navigate to `/settings` — confirm it redirects to `/settings/profile` and renders the Profile & Security tab with working Display Name save, Email save, Test email button, Recovery Code generation, and Change Password form (same behavior as before, just alone on its own tab for now).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/App.tsx frontend/src/pages/Settings.tsx frontend/src/pages/settings/ProfileTab.tsx
git commit -m "Split Settings into tabbed sub-pages: shell + Profile & Security (1/7)

Settings.tsx becomes a thin shell (tab sub-nav + nested routes);
Profile/Email/Recovery Code/Change Password move to settings/ProfileTab.tsx.
Remaining sections move in following tasks -- not independently
shippable mid-refactor, see plan Global Constraints."
```

---

### Task 3: Preferences tab (with the new pinned-items picker)

**Files:**
- Create: `frontend/src/pages/settings/PreferencesTab.tsx`
- Modify: `frontend/src/pages/Settings.tsx` (add the tab + route)

**Interfaces:**
- Consumes: `PINNABLE_ITEMS`, `loadPinnedNav`, `PINNED_STORAGE_KEY` from `../../lib/navItems` (Task 1); `getTheme`/`setTheme` from `../../store/theme`; `authApi` from `../../api`.
- Produces: nothing new consumed by later tasks.

This is where the "select favorites" feature actually lives — the pinned-items checklist described in the design spec.

- [ ] **Step 1: Create the Preferences tab**

Moves: Dark Mode toggle, Setup Wizard button, Suggested Transfer Increment (from the old `Settings.tsx`'s Preferences section, lines 384-395 and 396-410 and 426-449). Does NOT move the old "Navigation Order" up/down-arrow block (lines 411-425) or its backing state (`ALL_NAV_ITEMS`/`navOrder`/`moveNav`/`resetNavOrder`, lines 252-287) — those are deleted outright, replaced by the picker below.

```tsx
// frontend/src/pages/settings/PreferencesTab.tsx
import { useState, useEffect } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { authApi } from "../../api";
import { getTheme, setTheme } from "../../store/theme";
import { Moon, Sun, Wand2 } from "lucide-react";
import { PINNABLE_ITEMS, loadPinnedNav, PINNED_STORAGE_KEY } from "../../lib/navItems";

export default function PreferencesTab() {
  const [dark, setDark] = useState(getTheme() === "dark");
  function toggleDark() { const next = !dark; setDark(next); setTheme(next); }

  // Seeded from the server so the displayed value matches the current
  // setting on load, same as the original Settings.tsx's shared `me` effect.
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: authApi.me });
  const [transferIncrement, setTransferIncrement] = useState("");
  useEffect(() => { if (me) setTransferIncrement(me.transfer_increment ?? "1000"); }, [me]);
  const taxMut = useMutation({ mutationFn: authApi.updateMe });

  const [pinned, setPinned] = useState<string[]>(loadPinnedNav);
  function togglePin(to: string) {
    const next = pinned.includes(to) ? pinned.filter(t => t !== to) : [...pinned, to];
    setPinned(next);
    localStorage.setItem(PINNED_STORAGE_KEY, JSON.stringify(next));
    window.dispatchEvent(new CustomEvent("nav-order-changed"));
  }

  return (
    <div className="card">
      <h3 className="font-semibold text-gray-900 dark:text-gray-100 mb-4">Preferences</h3>
      <div className="flex items-center justify-between py-2">
        <div className="flex items-center gap-3">
          {dark ? <Moon size={16} className="text-indigo-400" /> : <Sun size={16} className="text-amber-500" />}
          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Dark Mode</span>
        </div>
        <button
          onClick={toggleDark}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${dark ? "bg-indigo-600" : "bg-gray-200"}`}
        >
          <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${dark ? "translate-x-6" : "translate-x-1"}`} />
        </button>
      </div>
      <div className="flex items-center justify-between py-2 border-t border-gray-100 dark:border-gray-700">
        <div className="flex items-center gap-3">
          <Wand2 size={16} className="text-indigo-400" />
          <div>
            <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Setup Wizard</span>
            <p className="text-xs text-gray-400">Add an account and income recurring item</p>
          </div>
        </div>
        <button
          onClick={() => window.dispatchEvent(new Event("open-wizard"))}
          className="btn-secondary text-sm px-3 py-1.5"
        >
          Open
        </button>
      </div>
      <div className="pt-3 border-t border-gray-100 dark:border-gray-700">
        <div className="mb-2">
          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Pinned Sidebar Items</span>
          <p className="text-xs text-gray-400">Dashboard is always pinned. Choose a few more for quick access above the grouped sections.</p>
        </div>
        <div className="space-y-1">
          {PINNABLE_ITEMS.map(item => (
            <label key={item.to} className="flex items-center gap-2 py-1 px-2 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700/50 cursor-pointer">
              <input
                type="checkbox"
                className="w-4 h-4 rounded accent-indigo-600"
                checked={pinned.includes(item.to)}
                onChange={() => togglePin(item.to)}
              />
              <item.icon size={14} className="text-gray-400" />
              <span className="text-sm text-gray-700 dark:text-gray-300">{item.label}</span>
            </label>
          ))}
        </div>
      </div>
      <div className="pt-3 border-t border-gray-100 dark:border-gray-700">
        <div className="flex items-center justify-between gap-3">
          <div>
            <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Suggested Transfer Increment</span>
            <p className="text-xs text-gray-400">Suggested transfers round up to this amount (e.g. $1,000 steps)</p>
          </div>
          <div className="flex items-center gap-2">
            <input
              type="number"
              step="1"
              className="input w-28 text-sm text-right"
              value={transferIncrement}
              onChange={(e) => setTransferIncrement(e.target.value)}
            />
            <button
              onClick={() => taxMut.mutate({ transfer_increment: transferIncrement ? parseFloat(transferIncrement) : null })}
              disabled={taxMut.isPending}
              className="btn-secondary text-xs px-3 py-1.5"
            >
              {taxMut.isPending ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
```

This mirrors how the original monolithic `Settings.tsx` seeded `transferIncrement` from `me.transfer_increment` via its shared `useEffect` (lines 202-222) — moved here as its own small, self-contained `useQuery`/`useEffect` pair since this tab doesn't otherwise need the rest of that original effect's fields (those belong to `ProfileTab`/`TaxTab`).

- [ ] **Step 2: Add the tab to the shell**

In `frontend/src/pages/Settings.tsx`, add the import and both the `TABS` entry and the route:

```tsx
import { SlidersHorizontal, User } from "lucide-react";
import PreferencesTab from "./settings/PreferencesTab";

const TABS = [
  { to: "profile", label: "Profile & Security", icon: User },
  { to: "preferences", label: "Preferences", icon: SlidersHorizontal },
];
```

```tsx
<Route path="preferences" element={<PreferencesTab />} />
```

(Add this `<Route>` line directly below the existing `profile` route inside the same `<Routes>` block.)

- [ ] **Step 3: Run tsc to verify**

Run: `cd frontend && npx tsc -b 2>&1 | grep -c "error TS"`
Expected: `11` (unchanged from Task 2's end state — no new errors, none fixed here).

If `SlidersHorizontal` isn't a valid export from the installed `lucide-react` version, tsc will fail immediately on that import — substitute any other reasonable lucide-react icon name (e.g. `Settings2`) and re-run.

- [ ] **Step 4: Manual verification**

`/settings/preferences` renders Dark Mode toggle, Setup Wizard button, the Pinned Sidebar Items checklist, and Suggested Transfer Increment. Check a box, confirm the sidebar (Task 1's work) picks it up live without a reload (the `nav-order-changed` event). Uncheck it, confirm it disappears from the pinned row and reappears in its group.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/settings/PreferencesTab.tsx frontend/src/pages/Settings.tsx
git commit -m "Split Settings into tabbed sub-pages: Preferences + pinned-items picker (2/7)

Dark mode, setup wizard, transfer increment move to settings/PreferencesTab.tsx.
The old up/down-arrow nav-order UI is gone -- replaced by the checkbox
picker over Task 1's pinnedNav model."
```

---

### Task 4: Accounts & Bank Sync tab

**Files:**
- Create: `frontend/src/pages/settings/AccountsTab.tsx`
- Modify: `frontend/src/pages/Settings.tsx` (add the tab + route)

**Interfaces:**
- Consumes: `accountsApi`, `cardsApi`, `bankSyncApi` from `../../api`; `fmt` from `../../lib/utils`.
- Produces: nothing new consumed by later tasks.

- [ ] **Step 1: Create the Accounts & Bank Sync tab**

Moves the Accounts section (old `Settings.tsx` lines 453-500) and Bank Connections section (lines 502-605) verbatim, plus their backing state/mutations (lines 25-78, 90-117). Both sections keep their own `<div className="card">` wrapper (two cards stacked, matching how they were two separate accordion cards before — just always-expanded now, no accordion chevron needed since each tab is its own screen already).

```tsx
// frontend/src/pages/settings/AccountsTab.tsx
import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { accountsApi, cardsApi, bankSyncApi } from "../../api";
import { fmt } from "../../lib/utils";
import { Plus, Pencil, Trash2, X, Check, AlertTriangle, Link } from "lucide-react";

const emptyAccount = { name: "", type: "checking", current_balance: "0", low_balance_threshold: "", interest_rate: "", notes: "" };

export default function AccountsTab() {
  const qc = useQueryClient();
  const { data: accounts = [] } = useQuery({ queryKey: ["accounts"], queryFn: accountsApi.list });
  // Credit cards are linkable sync targets too -- the mapping dropdown below
  // offers them alongside checking accounts.
  const { data: cards = [] } = useQuery<any[]>({ queryKey: ["credit-cards"], queryFn: cardsApi.list });
  const { data: bankConnections = [] } = useQuery<any[]>({ queryKey: ["bank-connections"], queryFn: bankSyncApi.status });
  const [setupToken, setSetupToken] = useState("");
  const [pendingConnect, setPendingConnect] = useState<{ connection_id: number; accounts: any[] } | null>(null);
  const [linkTargets, setLinkTargets] = useState<Record<string, string>>({});

  const connectMut = useMutation({
    mutationFn: (token: string) => bankSyncApi.connect(token),
    onSuccess: (data) => { setPendingConnect(data); setSetupToken(""); },
  });
  const linkMut = useMutation({
    mutationFn: ({ connectionId, data }: any) => bankSyncApi.link(connectionId, data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["bank-connections"] }); },
  });
  // Re-opens the mapping UI for a connection whose /connect response is long
  // gone -- without this, an unmapped account needs a whole new setup token.
  const loadAccountsMut = useMutation({
    mutationFn: (connectionId: number) => bankSyncApi.accounts(connectionId),
    onSuccess: (accts: any[], connectionId: number) =>
      setPendingConnect({ connection_id: connectionId, accounts: accts }),
  });
  const syncNowMut = useMutation({
    mutationFn: bankSyncApi.syncNow,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bank-connections"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
      // A sync updates linked card balances too, so refresh both keys the
      // codebase uses for credit cards.
      qc.invalidateQueries({ queryKey: ["credit-cards"] });
      qc.invalidateQueries({ queryKey: ["cards"] });
    },
  });
  const disconnectMut = useMutation({
    mutationFn: bankSyncApi.disconnect,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["bank-connections"] }),
  });

  function submitLink(simplefinAccountId: string, simplefinAccountName: string, connectionId: number) {
    const target = linkTargets[simplefinAccountId];
    if (!target) return;
    const [kind, id] = target.split(":");
    linkMut.mutate({
      connectionId,
      data: {
        simplefin_account_id: simplefinAccountId,
        simplefin_account_name: simplefinAccountName,
        local_account_id: kind === "account" ? parseInt(id) : undefined,
        local_credit_card_id: kind === "card" ? parseInt(id) : undefined,
      },
    });
  }

  const [showAccForm, setShowAccForm] = useState(false);
  const [editAcc, setEditAcc] = useState<any | null>(null);
  const [accForm, setAccForm] = useState({ ...emptyAccount });
  const [deleteAccId, setDeleteAccId] = useState<number | null>(null);
  const [editBalId, setEditBalId] = useState<number | null>(null);
  const [newBal, setNewBal] = useState("");
  const createAccMut = useMutation({ mutationFn: accountsApi.create, onSuccess: () => { qc.invalidateQueries({ queryKey: ["accounts"] }); setShowAccForm(false); } });
  const updateAccMut = useMutation({ mutationFn: ({ id, data }: any) => accountsApi.update(id, data), onSuccess: () => { qc.invalidateQueries({ queryKey: ["accounts"] }); setEditAcc(null); setShowAccForm(false); setEditBalId(null); } });
  const deleteAccMut = useMutation({ mutationFn: accountsApi.remove, onSuccess: () => { qc.invalidateQueries({ queryKey: ["accounts"] }); setDeleteAccId(null); } });

  function submitAcc(e: React.FormEvent) {
    e.preventDefault();
    const data = {
      ...accForm,
      current_balance: parseFloat(accForm.current_balance),
      low_balance_threshold: accForm.low_balance_threshold ? parseFloat(accForm.low_balance_threshold) : null,
      interest_rate: accForm.interest_rate ? parseFloat(accForm.interest_rate) : null,
    };
    if (editAcc) updateAccMut.mutate({ id: editAcc.id, data });
    else createAccMut.mutate(data);
  }
  function openNewAcc() { setAccForm({ ...emptyAccount }); setEditAcc(null); setShowAccForm(true); }
  function openEditAcc(a: any) {
    setEditAcc(a);
    setAccForm({ name: a.name, type: a.type, current_balance: a.current_balance, low_balance_threshold: a.low_balance_threshold ?? "", interest_rate: a.interest_rate ?? "", notes: a.notes ?? "" });
    setShowAccForm(true);
  }

  return (
    <div className="space-y-6">
      {/* ── Accounts ── */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100">Accounts</h3>
          <button onClick={openNewAcc} className="btn-primary btn-sm text-xs px-3 py-1.5"><Plus size={14} /> Add Account</button>
        </div>
        <div className="divide-y divide-gray-100 dark:divide-gray-700">
          {accounts.map((a: any) => (
            <div key={a.id} className="py-3 flex items-center justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <p className="text-sm font-medium text-gray-900 dark:text-gray-100">{a.name}</p>
                  {a.low_balance_threshold && parseFloat(a.current_balance) < parseFloat(a.low_balance_threshold) && (
                    <AlertTriangle size={14} className="text-amber-500" />
                  )}
                </div>
                <p className="text-xs text-gray-500 dark:text-gray-400 capitalize">{a.type.replace("_", " ")}</p>
                {a.low_balance_threshold && (
                  <p className="text-xs text-amber-600 dark:text-amber-400">Alert below {fmt(a.low_balance_threshold)}</p>
                )}
              </div>
              <div className="flex items-center gap-3">
                {editBalId === a.id ? (
                  <div className="flex flex-col items-end gap-1">
                    <div className="flex items-center gap-1">
                      <input type="number" step="0.01" className="input w-28 py-1 text-right" value={newBal} onChange={e => setNewBal(e.target.value)} autoFocus />
                      <button onClick={() => updateAccMut.mutate({ id: a.id, data: { current_balance: parseFloat(newBal) } })} className="text-green-600"><Check size={14} /></button>
                      <button onClick={() => setEditBalId(null)} className="text-gray-400"><X size={14} /></button>
                    </div>
                  </div>
                ) : (
                  <button onClick={() => { setEditBalId(a.id); setNewBal(a.current_balance); }} className="text-sm font-bold text-gray-900 dark:text-gray-100 tabular-nums hover:text-indigo-600 transition-colors" title="Click to correct balance">
                    {fmt(a.current_balance)}
                  </button>
                )}
                <button onClick={() => openEditAcc(a)} className="btn-ghost p-1.5"><Pencil size={14} /></button>
                <button onClick={() => setDeleteAccId(a.id)} className="btn-ghost p-1.5 text-red-400 hover:bg-red-50"><Trash2 size={14} /></button>
              </div>
            </div>
          ))}
          {accounts.length === 0 && <p className="text-sm text-gray-400 py-4 text-center">No accounts yet</p>}
        </div>
      </div>

      {/* ── Bank Connections ── */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100 flex items-center gap-2"><Link size={16} className="text-indigo-500" /> Bank Connections</h3>
          {bankConnections.length > 0 && (
            <button onClick={() => syncNowMut.mutate()} disabled={syncNowMut.isPending} className="btn-primary btn-sm text-xs px-3 py-1.5">
              {syncNowMut.isPending ? "Syncing…" : "Sync Now"}
            </button>
          )}
        </div>
        <div className="space-y-4">
          <p className="text-xs text-gray-500 dark:text-gray-400">
            Connects to your bank via SimpleFIN Bridge (~$15/yr, read-only) to pull transactions automatically. Syncs daily at 5am.
          </p>

          {bankConnections.map((conn: any) => (
            <div key={conn.id} className="border border-gray-100 dark:border-gray-700 rounded-lg p-3">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                    Connection #{conn.id} — {conn.status}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {conn.last_synced_at ? `Last synced ${new Date(conn.last_synced_at).toLocaleString()}` : "Never synced"}
                  </p>
                  {conn.last_error && <p className="text-xs text-red-600 dark:text-red-400 flex items-center gap-1"><AlertTriangle size={12} /> {conn.last_error}</p>}
                </div>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => loadAccountsMut.mutate(conn.id)}
                    disabled={loadAccountsMut.isPending}
                    className="btn-ghost text-xs px-2 py-1 text-indigo-500 hover:bg-indigo-50"
                  >
                    {loadAccountsMut.isPending && loadAccountsMut.variables === conn.id ? "Loading…" : "Map more accounts"}
                  </button>
                  <button onClick={() => disconnectMut.mutate(conn.id)} className="btn-ghost p-1.5 text-red-400 hover:bg-red-50"><Trash2 size={14} /></button>
                </div>
              </div>
              {conn.links.length > 0 && (
                <div className="mt-2 divide-y divide-gray-100 dark:divide-gray-700">
                  {conn.links.map((l: any) => (
                    <div key={l.id} className="py-1.5 text-xs text-gray-600 dark:text-gray-300">
                      {l.simplefin_account_name} → {l.local_account_id ? "linked account" : l.local_credit_card_id ? "linked card" : "unlinked"}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}

          {pendingConnect && (
            <div className="border border-indigo-200 dark:border-indigo-800 rounded-lg p-3 space-y-2">
              <p className="text-sm font-medium text-gray-900 dark:text-gray-100">Map discovered accounts</p>
              {pendingConnect.accounts.map((a: any) => (
                <div key={a.simplefin_account_id} className="flex items-center justify-between gap-2">
                  <span className="text-xs text-gray-600 dark:text-gray-300">{a.org_name} — {a.name} ({fmt(a.balance)})</span>
                  <select
                    className="input py-1 text-xs w-40"
                    value={linkTargets[a.simplefin_account_id] || ""}
                    onChange={(e) => setLinkTargets({ ...linkTargets, [a.simplefin_account_id]: e.target.value })}
                  >
                    <option value="">Select account or card…</option>
                    <optgroup label="Accounts">
                      {accounts.map((acc: any) => <option key={`account:${acc.id}`} value={`account:${acc.id}`}>{acc.name}</option>)}
                    </optgroup>
                    <optgroup label="Credit Cards">
                      {cards.map((c: any) => <option key={`card:${c.id}`} value={`card:${c.id}`}>{c.name}</option>)}
                    </optgroup>
                  </select>
                  <button
                    onClick={() => submitLink(a.simplefin_account_id, a.name, pendingConnect.connection_id)}
                    disabled={!linkTargets[a.simplefin_account_id]}
                    className="btn-primary btn-sm text-xs px-2 py-1"
                  >
                    Link
                  </button>
                </div>
              ))}
              <button onClick={() => setPendingConnect(null)} className="text-xs text-gray-400 hover:text-gray-600">Done</button>
            </div>
          )}

          <div className="flex items-center gap-2">
            <input
              type="text"
              className="input flex-1 text-xs"
              placeholder="Paste SimpleFIN setup token"
              value={setupToken}
              onChange={(e) => setSetupToken(e.target.value)}
            />
            <button
              onClick={() => connectMut.mutate(setupToken)}
              disabled={!setupToken || connectMut.isPending}
              className="btn-primary btn-sm text-xs px-3 py-1.5"
            >
              {connectMut.isPending ? "Connecting…" : "Connect"}
            </button>
          </div>
          {connectMut.isError && <p className="text-xs text-red-600 dark:text-red-400">{(connectMut.error as any)?.response?.data?.detail || "Failed to connect"}</p>}
        </div>
      </div>

      {/* ── Add/Edit Account modal ── */}
      {showAccForm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-sm">
            <div className="flex justify-between items-center mb-5">
              <h3 className="font-bold text-gray-900 dark:text-gray-100">{editAcc ? "Edit Account" : "Add Account"}</h3>
              <button onClick={() => setShowAccForm(false)} className="btn-ghost p-1"><X size={18} /></button>
            </div>
            <form onSubmit={submitAcc} className="space-y-3">
              <div><label className="label">Name</label><input className="input" placeholder="Main Checking" value={accForm.name} onChange={e => setAccForm({ ...accForm, name: e.target.value })} required /></div>
              <div>
                <label className="label">Type</label>
                <select className="input" value={accForm.type} onChange={e => setAccForm({ ...accForm, type: e.target.value })}>
                  <option value="checking">Checking</option>
                  <option value="savings">Savings</option>
                  <option value="money_market">Money Market</option>
                </select>
              </div>
              <div><label className="label">Current Balance</label><input type="number" step="0.01" className="input" value={accForm.current_balance} onChange={e => setAccForm({ ...accForm, current_balance: e.target.value })} /></div>
              <div><label className="label">Warn When Balance Drops Below (optional)</label><input type="number" step="0.01" className="input" placeholder="e.g. 1000" value={accForm.low_balance_threshold} onChange={e => setAccForm({ ...accForm, low_balance_threshold: e.target.value })} /></div>
              <div><label className="label">Annual Interest Rate % (optional, for savings/HYSA)</label><input type="number" step="0.01" className="input" placeholder="e.g. 4.5" value={accForm.interest_rate} onChange={e => setAccForm({ ...accForm, interest_rate: e.target.value })} /></div>
              <div><label className="label">Notes</label><input className="input" value={accForm.notes} onChange={e => setAccForm({ ...accForm, notes: e.target.value })} /></div>
              <div className="flex gap-3 pt-2">
                <button type="submit" className="btn-primary flex-1">{editAcc ? "Save" : "Add"}</button>
                <button type="button" onClick={() => setShowAccForm(false)} className="btn-secondary flex-1">Cancel</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── Delete account confirm ── */}
      {deleteAccId && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-sm text-center">
            <h3 className="font-bold text-gray-900 dark:text-gray-100 mb-1">Remove this account?</h3>
            <p className="text-sm text-gray-500 mb-5">It will be hidden but data is preserved.</p>
            <div className="flex gap-3">
              <button onClick={() => deleteAccMut.mutate(deleteAccId)} className="btn-danger flex-1">Remove</button>
              <button onClick={() => setDeleteAccId(null)} className="btn-secondary flex-1">Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add the tab to the shell**

In `frontend/src/pages/Settings.tsx`:

```tsx
import { Link } from "lucide-react";
import AccountsTab from "./settings/AccountsTab";
```

```tsx
{ to: "accounts", label: "Accounts & Bank Sync", icon: Link },
```

```tsx
<Route path="accounts" element={<AccountsTab />} />
```

- [ ] **Step 3: Run tsc to verify**

Run: `cd frontend && npx tsc -b 2>&1 | grep -c "error TS"`
Expected: `11` (unchanged).

- [ ] **Step 4: Manual verification**

`/settings/accounts` shows both Accounts and Bank Connections cards with all existing functionality (add/edit/delete account, inline balance edit, connect/sync/disconnect bank, map discovered accounts).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/settings/AccountsTab.tsx frontend/src/pages/Settings.tsx
git commit -m "Split Settings into tabbed sub-pages: Accounts & Bank Sync (3/7)"
```

---

### Task 5: Update the two deep-links to Accounts

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx:441`
- Modify: `frontend/src/pages/Spending.tsx:623` (tax link -- see note below, this one actually points at Task 6's tab, done here anyway since it's a one-line change with no dependency on Task 6 landing first)

**Interfaces:** none.

- [ ] **Step 1: Update Dashboard.tsx's Add Account button**

In `frontend/src/pages/Dashboard.tsx`, change:
```tsx
<button onClick={() => navigate("/settings")} className="btn-primary">Add Account</button>
```
to:
```tsx
<button onClick={() => navigate("/settings/accounts")} className="btn-primary">Add Account</button>
```

- [ ] **Step 2: Update Spending.tsx's tax-estimate error link**

In `frontend/src/pages/Spending.tsx`, change:
```tsx
{taxEstimate.error} <a href="/settings" className="underline ml-1">Go to Settings</a>
```
to:
```tsx
{taxEstimate.error} <a href="/settings/tax" className="underline ml-1">Go to Settings</a>
```

(This points at a route that doesn't exist until Task 6 lands -- that's fine, it 404s to nothing worse than today's behavior in the interim, since Task 6 lands in the same overall plan execution before this is considered done. If you're executing tasks out of order for some reason, sequence this after Task 6 instead.)

- [ ] **Step 3: Run tsc to verify**

Run: `cd frontend && npx tsc -b 2>&1 | grep -c "error TS"`
Expected: `11` (unchanged -- these are plain string literal changes).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Dashboard.tsx frontend/src/pages/Spending.tsx
git commit -m "Point Settings deep-links at their specific tabs, not the bare page"
```

---

### Task 6: Categories & Rules tab

**Files:**
- Create: `frontend/src/pages/settings/CategoriesTab.tsx`
- Modify: `frontend/src/pages/Settings.tsx` (add the tab + route)

**Interfaces:**
- Consumes: `categoriesApi`, `budgetApi`, `rulesApi` from `../../api`; `fmt` from `../../lib/utils`.
- Produces: nothing new consumed by later tasks.

The pre-existing `openNewCat` type error (see Global Constraints) already disappeared in Task 2 along with the rest of the old monolithic file — this task writes `openNewCat` correctly from scratch in its new home so the bug is never reintroduced.

- [ ] **Step 1: Create the Categories & Rules tab**

Moves the Categories section (old `Settings.tsx` lines 607-658) and Transaction Rules section (lines 660-695) verbatim, plus their state (lines 79-80, 119-154, 289-317), plus the Add/Edit Category modal (1204-1260), Delete Category confirm (1262-1274), Add/Edit Rule modal (1315-1380), Delete Rule confirm (1382-1394). The version below writes `openNewCat` correctly: the original was missing `tax_deductible` in its `setCatForm(...)` call (why it was one of the two pre-existing tsc errors called out in Global Constraints) -- this version includes `tax_deductible: parentCat?.tax_deductible ?? false` to match `catForm`'s inferred type from `emptyCat`, so the bug doesn't come back.

```tsx
// frontend/src/pages/settings/CategoriesTab.tsx
import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { categoriesApi, budgetApi, rulesApi } from "../../api";
import { fmt } from "../../lib/utils";
import { Plus, Pencil, Trash2, X, Check, ChevronRight, ChevronDown } from "lucide-react";

const emptyCat = { name: "", type: "expense", parent_id: "", color: "#6366f1", tax_deductible: false };
const COLOR_SWATCHES = ["#6366f1", "#22c55e", "#ef4444", "#f59e0b", "#3b82f6", "#8b5cf6", "#ec4899", "#14b8a6"];

export default function CategoriesTab() {
  const qc = useQueryClient();
  const currentYear = new Date().getFullYear();
  const { data: categories = [] } = useQuery<any[]>({ queryKey: ["categories"], queryFn: categoriesApi.list });
  const { data: budgets = [] } = useQuery<any[]>({ queryKey: ["budget", currentYear], queryFn: () => budgetApi.list(currentYear) });

  const [showCatForm, setShowCatForm] = useState(false);
  const [editCat, setEditCat] = useState<any | null>(null);
  const [catForm, setCatForm] = useState({ ...emptyCat });
  const [deleteCatId, setDeleteCatId] = useState<number | null>(null);
  const [editBudgetCatId, setEditBudgetCatId] = useState<number | null>(null);
  const [budgetDraft, setBudgetDraft] = useState("");
  const [expandedCats, setExpandedCats] = useState<Set<number>>(new Set());

  const budgetMap: Record<number, string> = {};
  budgets.forEach((b: any) => { budgetMap[b.category_id] = b.budgeted_amount; });

  const createCatMut = useMutation({ mutationFn: categoriesApi.create, onSuccess: () => { qc.invalidateQueries({ queryKey: ["categories"] }); setShowCatForm(false); } });
  const updateCatMut = useMutation({ mutationFn: ({ id, data }: any) => categoriesApi.update(id, data), onSuccess: () => { qc.invalidateQueries({ queryKey: ["categories"] }); setEditCat(null); setShowCatForm(false); } });
  const deleteCatMut = useMutation({ mutationFn: categoriesApi.remove, onSuccess: () => { qc.invalidateQueries({ queryKey: ["categories"] }); setDeleteCatId(null); } });
  const upsertBudgetMut = useMutation({ mutationFn: budgetApi.upsert, onSuccess: () => { qc.invalidateQueries({ queryKey: ["budget", currentYear] }); setEditBudgetCatId(null); } });

  function submitCat(e: React.FormEvent) {
    e.preventDefault();
    const data = { ...catForm, parent_id: catForm.parent_id ? parseInt(catForm.parent_id) : null };
    if (editCat) updateCatMut.mutate({ id: editCat.id, data });
    else createCatMut.mutate(data);
  }
  function openNewCat(parentCat?: any) {
    setCatForm({
      name: "",
      type: parentCat?.type ?? "expense",
      parent_id: parentCat?.id?.toString() ?? "",
      color: "#6366f1",
      tax_deductible: parentCat?.tax_deductible ?? false,
    });
    setEditCat(null);
    setShowCatForm(true);
  }
  function openEditCat(c: any) {
    setEditCat(c);
    setCatForm({ name: c.name, type: c.type, parent_id: c.parent_id?.toString() ?? "", color: c.color, tax_deductible: c.tax_deductible ?? false });
    setShowCatForm(true);
  }
  function saveBudget(catId: number) {
    upsertBudgetMut.mutate({ category_id: catId, year: currentYear, month: 0, budgeted_amount: parseFloat(budgetDraft) || 0 });
  }

  const { data: rules = [] } = useQuery<any[]>({ queryKey: ["rules"], queryFn: rulesApi.list });
  const emptyRule = { name: "", field: "description", pattern_type: "contains", pattern: "", action: "set_category", category_id: "", priority: "0" };
  const [showRuleForm, setShowRuleForm] = useState(false);
  const [editRule, setEditRule] = useState<any | null>(null);
  const [ruleForm, setRuleForm] = useState({ ...emptyRule });
  const [deleteRuleId, setDeleteRuleId] = useState<number | null>(null);
  const [ruleTestDesc, setRuleTestDesc] = useState("");
  const [ruleTestResult, setRuleTestResult] = useState<boolean | null>(null);
  const createRuleMut = useMutation({ mutationFn: rulesApi.create, onSuccess: () => { qc.invalidateQueries({ queryKey: ["rules"] }); setShowRuleForm(false); } });
  const updateRuleMut = useMutation({ mutationFn: ({ id, data }: any) => rulesApi.update(id, data), onSuccess: () => { qc.invalidateQueries({ queryKey: ["rules"] }); setEditRule(null); setShowRuleForm(false); } });
  const deleteRuleMut = useMutation({ mutationFn: rulesApi.remove, onSuccess: () => { qc.invalidateQueries({ queryKey: ["rules"] }); setDeleteRuleId(null); } });
  function submitRule(e: React.FormEvent) {
    e.preventDefault();
    const data = { ...ruleForm, priority: parseInt(ruleForm.priority) || 0, category_id: ruleForm.category_id ? parseInt(ruleForm.category_id) : null };
    if (editRule) updateRuleMut.mutate({ id: editRule.id, data });
    else createRuleMut.mutate(data);
  }
  function openEditRule(r: any) {
    setEditRule(r);
    setRuleForm({ name: r.name, field: r.field, pattern_type: r.pattern_type, pattern: r.pattern, action: r.action, category_id: r.category_id?.toString() ?? "", priority: r.priority.toString() });
    setRuleTestDesc(""); setRuleTestResult(null);
    setShowRuleForm(true);
  }
  function handleTestRule() {
    if (!ruleTestDesc || !ruleForm.pattern) return;
    rulesApi.test({ pattern: ruleForm.pattern, pattern_type: ruleForm.pattern_type, description: ruleTestDesc })
      .then((r: any) => setRuleTestResult(r.matched));
  }

  return (
    <div className="space-y-6">
      {/* ── Categories ── */}
      <div className="card">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100">Categories</h3>
          <button onClick={() => openNewCat()} className="btn-primary btn-sm text-xs px-3 py-1.5"><Plus size={14} /> Add Category</button>
        </div>
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">Click a budget amount to edit it inline</p>
        <div className="space-y-1">
          {categories.map((cat: any) => (
            <div key={cat.id}>
              <div className="flex items-center gap-2 py-2 rounded-lg px-2 hover:bg-gray-50 dark:hover:bg-gray-700/50">
                <button onClick={() => setExpandedCats(prev => { const s = new Set(prev); s.has(cat.id) ? s.delete(cat.id) : s.add(cat.id); return s; })} className="text-gray-400">
                  {expandedCats.has(cat.id) ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                </button>
                <div className="w-3 h-3 rounded-full shrink-0" style={{ background: cat.color }} />
                <span className="text-sm font-semibold text-gray-900 dark:text-gray-100 flex-1">{cat.name}</span>
                <span className="text-xs text-gray-400 capitalize">{cat.type}</span>
                <button onClick={() => openNewCat(cat)} className="btn-ghost p-1 text-xs text-indigo-500" title="Add sub-category"><Plus size={12} /></button>
                <button onClick={() => openEditCat(cat)} className="btn-ghost p-1"><Pencil size={12} /></button>
                <button onClick={() => setDeleteCatId(cat.id)} className="btn-ghost p-1 text-red-400" disabled={cat.children?.length > 0}><Trash2 size={12} /></button>
              </div>
              {expandedCats.has(cat.id) && cat.children?.map((ch: any) => (
                <div key={ch.id} className="flex items-center gap-2 py-1.5 pl-9 pr-2 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700/50">
                  <div className="w-2 h-2 rounded-full shrink-0" style={{ background: ch.color }} />
                  <span className="text-sm text-gray-700 dark:text-gray-300 flex-1">{ch.name}</span>
                  {editBudgetCatId === ch.id ? (
                    <div className="flex items-center gap-1">
                      <input type="number" step="0.01" className="input w-24 py-0.5 text-right text-xs" value={budgetDraft} onChange={e => setBudgetDraft(e.target.value)} autoFocus />
                      <button onClick={() => saveBudget(ch.id)} className="text-green-600"><Check size={12} /></button>
                      <button onClick={() => setEditBudgetCatId(null)} className="text-gray-400"><X size={12} /></button>
                    </div>
                  ) : (
                    <button onClick={() => { setEditBudgetCatId(ch.id); setBudgetDraft(budgetMap[ch.id] ?? "0"); }} className="text-xs text-gray-500 dark:text-gray-400 hover:text-indigo-600 tabular-nums min-w-[4rem] text-right">
                      {budgetMap[ch.id] ? fmt(budgetMap[ch.id]) : "set budget"}
                    </button>
                  )}
                  <button onClick={() => openEditCat(ch)} className="btn-ghost p-1"><Pencil size={12} /></button>
                  <button onClick={() => setDeleteCatId(ch.id)} className="btn-ghost p-1 text-red-400"><Trash2 size={12} /></button>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* ── Transaction Rules ── */}
      <div className="card">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100">Transaction Rules</h3>
          <button onClick={() => { setEditRule(null); setRuleForm({ ...emptyRule }); setRuleTestDesc(""); setRuleTestResult(null); setShowRuleForm(true); }} className="btn-primary btn-sm text-xs px-3 py-1.5"><Plus size={14} /> Add Rule</button>
        </div>
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">Auto-categorize transactions at import based on description patterns</p>
        {rules.length === 0 && <p className="text-sm text-gray-400 py-2">No rules yet. Add one to auto-categorize imports.</p>}
        {rules.length > 0 && (
          <div className="divide-y divide-gray-100 dark:divide-gray-700">
            {rules.map((r: any) => (
              <div key={r.id} className="py-2.5 flex items-center justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium text-gray-900 dark:text-gray-100">{r.name}</span>
                    {!r.is_active && <span className="text-xs text-gray-400 bg-gray-100 dark:bg-gray-700 px-1.5 py-0.5 rounded">inactive</span>}
                  </div>
                  <p className="text-xs text-gray-500 dark:text-gray-400 truncate">
                    {r.field} {r.pattern_type} <code className="bg-gray-100 dark:bg-gray-700 px-1 rounded">{r.pattern}</code>
                    {" → "}{r.action === "set_category" ? (categories.flatMap((c: any) => [c, ...(c.children ?? [])]).find((c: any) => c.id === r.category_id)?.name ?? "category") : "mark transfer"}
                  </p>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <button onClick={() => openEditRule(r)} className="btn-ghost p-1"><Pencil size={14} /></button>
                  <button onClick={() => setDeleteRuleId(r.id)} className="btn-ghost p-1 text-red-400"><Trash2 size={14} /></button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Add/Edit Category modal ── */}
      {showCatForm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-sm">
            <div className="flex justify-between items-center mb-5">
              <h3 className="font-bold text-gray-900 dark:text-gray-100">{editCat ? "Edit Category" : "Add Category"}</h3>
              <button onClick={() => setShowCatForm(false)} className="btn-ghost p-1"><X size={18} /></button>
            </div>
            <form onSubmit={submitCat} className="space-y-3">
              <div><label className="label">Name</label><input className="input" placeholder="Food & Drinks" value={catForm.name} onChange={e => setCatForm({ ...catForm, name: e.target.value })} required /></div>
              <div>
                <label className="label">Type</label>
                <select className="input" value={catForm.type} onChange={e => setCatForm({ ...catForm, type: e.target.value })}>
                  <option value="expense">Expense</option>
                  <option value="income">Income</option>
                  <option value="savings">Savings (excluded from spending totals)</option>
                </select>
              </div>
              <div>
                <label className="label">Parent Category (leave empty for top-level)</label>
                <select className="input" value={catForm.parent_id} onChange={e => setCatForm({ ...catForm, parent_id: e.target.value })}>
                  <option value="">None (top-level)</option>
                  {categories.filter((c: any) => !c.parent_id).map((c: any) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label">Color</label>
                <div className="flex gap-2 flex-wrap">
                  {COLOR_SWATCHES.map(c => (
                    <button key={c} type="button" onClick={() => setCatForm({ ...catForm, color: c })}
                      className={`w-7 h-7 rounded-full border-2 transition-transform ${catForm.color === c ? "border-gray-900 dark:border-white scale-110" : "border-transparent"}`}
                      style={{ background: c }} />
                  ))}
                  <input type="color" className="w-7 h-7 rounded-full cursor-pointer border-0 p-0" value={catForm.color} onChange={e => setCatForm({ ...catForm, color: e.target.value })} />
                </div>
              </div>
              {catForm.type === "expense" && (
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={catForm.tax_deductible}
                    onChange={e => setCatForm({ ...catForm, tax_deductible: e.target.checked })}
                    className="w-4 h-4 rounded accent-indigo-600"
                  />
                  <span className="text-sm text-gray-700 dark:text-gray-300">Tax deductible (include in Tax Export)</span>
                </label>
              )}
              <div className="flex gap-3 pt-2">
                <button type="submit" className="btn-primary flex-1">{editCat ? "Save" : "Add"}</button>
                <button type="button" onClick={() => setShowCatForm(false)} className="btn-secondary flex-1">Cancel</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── Delete category confirm ── */}
      {deleteCatId && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-sm text-center">
            <h3 className="font-bold text-gray-900 dark:text-gray-100 mb-1">Delete this category?</h3>
            <p className="text-sm text-gray-500 mb-5">Transactions in this category will become uncategorized.</p>
            <div className="flex gap-3">
              <button onClick={() => deleteCatMut.mutate(deleteCatId)} className="btn-danger flex-1">Delete</button>
              <button onClick={() => setDeleteCatId(null)} className="btn-secondary flex-1">Cancel</button>
            </div>
          </div>
        </div>
      )}

      {/* ── Add/Edit Rule modal ── */}
      {showRuleForm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-md">
            <div className="flex justify-between items-center mb-5">
              <h3 className="font-bold text-gray-900 dark:text-gray-100">{editRule ? "Edit Rule" : "Add Rule"}</h3>
              <button onClick={() => setShowRuleForm(false)} className="btn-ghost p-1"><X size={18} /></button>
            </div>
            <form onSubmit={submitRule} className="space-y-3">
              <div><label className="label">Rule Name</label><input className="input" placeholder="e.g. Spotify → Subscriptions" value={ruleForm.name} onChange={e => setRuleForm({ ...ruleForm, name: e.target.value })} required /></div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Pattern Type</label>
                  <select className="input" value={ruleForm.pattern_type} onChange={e => { setRuleForm({ ...ruleForm, pattern_type: e.target.value }); setRuleTestResult(null); }}>
                    <option value="contains">Contains</option>
                    <option value="startswith">Starts with</option>
                    <option value="regex">Regex</option>
                  </select>
                </div>
                <div>
                  <label className="label">Priority (higher runs first)</label>
                  <input type="number" className="input" value={ruleForm.priority} onChange={e => setRuleForm({ ...ruleForm, priority: e.target.value })} />
                </div>
              </div>
              <div>
                <label className="label">Pattern</label>
                <input className="input font-mono" placeholder={ruleForm.pattern_type === "regex" ? "e.g. SPOTIFY|NETFLIX" : "e.g. SPOTIFY"} value={ruleForm.pattern} onChange={e => { setRuleForm({ ...ruleForm, pattern: e.target.value }); setRuleTestResult(null); }} required />
              </div>
              <div>
                <label className="label">Action</label>
                <select className="input" value={ruleForm.action} onChange={e => setRuleForm({ ...ruleForm, action: e.target.value })}>
                  <option value="set_category">Set Category</option>
                  <option value="mark_transfer">Mark as Transfer</option>
                </select>
              </div>
              {ruleForm.action === "set_category" && (
                <div>
                  <label className="label">Category</label>
                  <select className="input" value={ruleForm.category_id} onChange={e => setRuleForm({ ...ruleForm, category_id: e.target.value })} required>
                    <option value="">Select…</option>
                    {categories.flatMap((c: any) => [c, ...(c.children ?? [])]).map((c: any) => (
                      <option key={c.id} value={c.id}>{c.parent_id ? "  " : ""}{c.name}</option>
                    ))}
                  </select>
                </div>
              )}
              <div className="border-t border-gray-100 dark:border-gray-700 pt-3">
                <label className="label">Live Test</label>
                <div className="flex gap-2">
                  <input className="input flex-1 text-sm" placeholder="Paste a transaction description…" value={ruleTestDesc} onChange={e => { setRuleTestDesc(e.target.value); setRuleTestResult(null); }} />
                  <button type="button" onClick={handleTestRule} className="btn-secondary text-sm px-3 shrink-0">Test</button>
                </div>
                {ruleTestResult !== null && (
                  <p className={`text-xs mt-1 ${ruleTestResult ? "text-green-600" : "text-red-500"}`}>
                    {ruleTestResult ? "✓ Pattern matches" : "✗ No match"}
                  </p>
                )}
              </div>
              <div className="flex gap-3 pt-2">
                <button type="submit" className="btn-primary flex-1">{editRule ? "Save" : "Add Rule"}</button>
                <button type="button" onClick={() => setShowRuleForm(false)} className="btn-secondary flex-1">Cancel</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── Delete Rule confirm ── */}
      {deleteRuleId && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-sm text-center">
            <h3 className="font-bold text-gray-900 dark:text-gray-100 mb-1">Delete this rule?</h3>
            <p className="text-sm text-gray-500 mb-5">Future imports won't use this rule. Existing transactions are unaffected.</p>
            <div className="flex gap-3">
              <button onClick={() => deleteRuleMut.mutate(deleteRuleId)} className="btn-danger flex-1">Delete</button>
              <button onClick={() => setDeleteRuleId(null)} className="btn-secondary flex-1">Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add the tab to the shell**

In `frontend/src/pages/Settings.tsx`:

```tsx
import { Tags } from "lucide-react";
import CategoriesTab from "./settings/CategoriesTab";
```

```tsx
{ to: "categories", label: "Categories & Rules", icon: Tags },
```

```tsx
<Route path="categories" element={<CategoriesTab />} />
```

- [ ] **Step 3: Run tsc to verify**

Run: `cd frontend && npx tsc -b 2>&1 | grep -c "error TS"`
Expected: `11` (unchanged -- the `openNewCat` fix happened when this code was still inside the now-deleted old `Settings.tsx`, in Task 2 Step 3; it's not being fixed again here, just correctly re-created in its new home).

If `Tags` isn't a valid `lucide-react` export in the installed version, substitute another reasonable icon (e.g. `Folder`) and re-run.

- [ ] **Step 4: Manual verification**

`/settings/categories` shows Categories (add/edit/delete, sub-categories, inline budget edit, color picker, tax-deductible checkbox) and Transaction Rules (add/edit/delete/test) with all existing functionality intact.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/settings/CategoriesTab.tsx frontend/src/pages/Settings.tsx
git commit -m "Split Settings into tabbed sub-pages: Categories & Rules (4/7)

Writes openNewCat with the tax_deductible field the original was
missing, so the type error that was in the old file (already gone
since Task 2 replaced it) doesn't come back in this new home."
```

---

### Task 7: Tax tab

**Files:**
- Create: `frontend/src/pages/settings/TaxTab.tsx`
- Modify: `frontend/src/pages/Settings.tsx` (add the tab + route)

**Interfaces:**
- Consumes: `authApi` from `../../api`.
- Produces: nothing new consumed by later tasks.

- [ ] **Step 1: Create the Tax tab**

Moves the Tax Profile block (old `Settings.tsx` lines 953-1059) and the Social Security state (lines 246-249), plus the tax-specific fields from the old shared `me`-driven `useEffect` (lines 202-222, the subset covering `taxFilingStatus` through `transferIncrement` -- note `transferIncrement` already moved to Task 3's `PreferencesTab`, don't duplicate it here) and `taxMut` (lines 196-200).

```tsx
// frontend/src/pages/settings/TaxTab.tsx
import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { authApi } from "../../api";

export default function TaxTab() {
  const qc = useQueryClient();
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: authApi.me });

  const [taxFilingStatus, setTaxFilingStatus] = useState("single");
  const [taxState, setTaxState] = useState("");
  const [taxSalary, setTaxSalary] = useState("");
  const [taxOtherIncome, setTaxOtherIncome] = useState("");
  const [taxFedWithheld, setTaxFedWithheld] = useState("");
  const [taxStateWithheld, setTaxStateWithheld] = useState("");
  const [taxMortgageInterest, setTaxMortgageInterest] = useState("");
  const [taxDonations, setTaxDonations] = useState("");
  const [taxSalt, setTaxSalt] = useState("");
  const [taxPropertyTax, setTaxPropertyTax] = useState("");
  const [taxOther, setTaxOther] = useState("");
  const [taxSaved, setTaxSaved] = useState(false);
  const [ssGross, setSsGross] = useState("");
  const [ssWageBase, setSsWageBase] = useState("");
  const [ssBonus, setSsBonus] = useState("");

  const taxMut = useMutation({
    mutationFn: authApi.updateMe,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["me"] }); setTaxSaved(true); setTimeout(() => setTaxSaved(false), 2000); },
  });

  useEffect(() => {
    if (me) {
      setSsGross(me.ss_gross_per_paycheck ?? "");
      setSsWageBase(me.ss_wage_base ?? "176100");
      setSsBonus(me.ss_bonus_ytd ?? "");
      setTaxFilingStatus(me.tax_filing_status ?? "single");
      setTaxState(me.tax_state ?? "");
      setTaxSalary(me.annual_salary ?? "");
      setTaxOtherIncome(me.other_income ?? "");
      setTaxFedWithheld(me.federal_withholding_ytd ?? "");
      setTaxStateWithheld(me.state_withholding_ytd ?? "");
      setTaxMortgageInterest(me.itemized_mortgage_interest ?? "");
      setTaxDonations(me.itemized_donations ?? "");
      setTaxSalt(me.itemized_salt ?? "");
      setTaxPropertyTax(me.itemized_property_tax ?? "");
      setTaxOther(me.itemized_other ?? "");
    }
  }, [me]);

  return (
    <div className="card">
      <div className="space-y-3">
        <h3 className="font-semibold text-gray-900 dark:text-gray-100">Tax Profile</h3>
        <p className="text-xs text-gray-500 dark:text-gray-400">Used to estimate your tax obligation in the Spending → Tax tab. All values are estimates — consult a tax professional.</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-xl">
          <div>
            <label className="label">Filing Status</label>
            <select className="input" value={taxFilingStatus} onChange={e => setTaxFilingStatus(e.target.value)}>
              <option value="single">Single</option>
              <option value="married_jointly">Married Filing Jointly</option>
              <option value="married_separately">Married Filing Separately</option>
              <option value="head_of_household">Head of Household</option>
            </select>
          </div>
          <div>
            <label className="label">State (2-letter code)</label>
            <input className="input uppercase" placeholder="e.g. TX" maxLength={2} value={taxState} onChange={e => setTaxState(e.target.value.toUpperCase())} />
          </div>
          <div>
            <label className="label">Annual Gross Salary (W-2)</label>
            <input type="number" step="1" className="input" placeholder="e.g. 85000" value={taxSalary} onChange={e => setTaxSalary(e.target.value)} />
          </div>
          <div>
            <label className="label">Other Income (1099, dividends, etc.)</label>
            <input type="number" step="1" className="input" placeholder="e.g. 5000" value={taxOtherIncome} onChange={e => setTaxOtherIncome(e.target.value)} />
          </div>
          <div>
            <label className="label">Federal Tax Withheld YTD</label>
            <input type="number" step="1" className="input" placeholder="From your pay stubs" value={taxFedWithheld} onChange={e => setTaxFedWithheld(e.target.value)} />
          </div>
          <div>
            <label className="label">State Tax Withheld YTD</label>
            <input type="number" step="1" className="input" placeholder="From your pay stubs" value={taxStateWithheld} onChange={e => setTaxStateWithheld(e.target.value)} />
          </div>
        </div>
        <div className="border-t border-gray-100 dark:border-gray-700 pt-3">
          <p className="text-xs font-medium text-gray-600 dark:text-gray-400 mb-2">Itemized Deductions (from tax documents)</p>
          <p className="text-xs text-gray-400 dark:text-gray-500 mb-3">These are added to any transactions marked tax-deductible. If the total exceeds the standard deduction, itemized will be used automatically.</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-xl">
            <div>
              <label className="label">Mortgage Interest (Form 1098)</label>
              <input type="number" step="0.01" className="input" placeholder="e.g. 35919.55" value={taxMortgageInterest} onChange={e => setTaxMortgageInterest(e.target.value)} />
            </div>
            <div>
              <label className="label">Charitable Donations</label>
              <input type="number" step="0.01" className="input" placeholder="e.g. 15600.00" value={taxDonations} onChange={e => setTaxDonations(e.target.value)} />
            </div>
            <div>
              <label className="label">State &amp; Local Taxes (SALT)</label>
              <input type="number" step="0.01" className="input" placeholder="e.g. 10506.24" value={taxSalt} onChange={e => setTaxSalt(e.target.value)} />
            </div>
            <div>
              <label className="label">Property Taxes</label>
              <input type="number" step="0.01" className="input" placeholder="e.g. 6000.00" value={taxPropertyTax} onChange={e => setTaxPropertyTax(e.target.value)} />
            </div>
            <div>
              <label className="label">Other Deductions (vehicle tax, etc.)</label>
              <input type="number" step="0.01" className="input" placeholder="e.g. 713.00" value={taxOther} onChange={e => setTaxOther(e.target.value)} />
            </div>
          </div>
        </div>
        <div className="border-t border-gray-100 dark:border-gray-700 pt-3">
          <div className="flex items-center gap-2 mb-1">
            <p className="text-xs font-medium text-gray-600 dark:text-gray-400">Social Security Tracker</p>
          </div>
          <p className="text-xs text-gray-400 dark:text-gray-500 mb-3">Track when you hit the SS wage base to plan for your resulting paycheck increase (~6.2% of gross). The 2025 wage base is $176,100.</p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 max-w-xl">
            <div>
              <label className="label">Gross Per Paycheck ($)</label>
              <input type="number" step="0.01" className="input" placeholder="5000" value={ssGross} onChange={e => setSsGross(e.target.value)} />
            </div>
            <div>
              <label className="label">SS Wage Base ($)</label>
              <input type="number" step="1" className="input" placeholder="176100" value={ssWageBase} onChange={e => setSsWageBase(e.target.value)} />
            </div>
            <div>
              <label className="label">YTD Bonus Subject to SS ($)</label>
              <input type="number" step="0.01" className="input" placeholder="0" value={ssBonus} onChange={e => setSsBonus(e.target.value)} />
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button
            className="btn-primary text-sm"
            disabled={taxMut.isPending}
            onClick={() => taxMut.mutate({
              tax_filing_status: taxFilingStatus,
              tax_state: taxState || null,
              annual_salary: taxSalary ? parseFloat(taxSalary) : null,
              other_income: taxOtherIncome ? parseFloat(taxOtherIncome) : null,
              federal_withholding_ytd: taxFedWithheld ? parseFloat(taxFedWithheld) : null,
              state_withholding_ytd: taxStateWithheld ? parseFloat(taxStateWithheld) : null,
              itemized_mortgage_interest: taxMortgageInterest ? parseFloat(taxMortgageInterest) : null,
              itemized_donations: taxDonations ? parseFloat(taxDonations) : null,
              itemized_salt: taxSalt ? parseFloat(taxSalt) : null,
              itemized_property_tax: taxPropertyTax ? parseFloat(taxPropertyTax) : null,
              itemized_other: taxOther ? parseFloat(taxOther) : null,
              ss_gross_per_paycheck: ssGross ? parseFloat(ssGross) : null,
              ss_wage_base: ssWageBase ? parseFloat(ssWageBase) : null,
              ss_bonus_ytd: ssBonus ? parseFloat(ssBonus) : null,
            })}
          >
            {taxMut.isPending ? "Saving…" : "Save Tax Profile"}
          </button>
          {taxSaved && <span className="text-sm text-green-600">Saved!</span>}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Add the tab to the shell**

In `frontend/src/pages/Settings.tsx`:

```tsx
import { Receipt } from "lucide-react";
import TaxTab from "./settings/TaxTab";
```

```tsx
{ to: "tax", label: "Tax", icon: Receipt },
```

```tsx
<Route path="tax" element={<TaxTab />} />
```

- [ ] **Step 3: Run tsc to verify**

Run: `cd frontend && npx tsc -b 2>&1 | grep -c "error TS"`
Expected: `11` (unchanged).

- [ ] **Step 4: Manual verification**

`/settings/tax` renders the full Tax Profile form (filing status through itemized deductions) and Social Security Tracker, values load from `me` on open, Save persists. `Spending.tsx`'s "Go to Settings" tax-estimate link (Task 5) now lands here correctly.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/settings/TaxTab.tsx frontend/src/pages/Settings.tsx
git commit -m "Split Settings into tabbed sub-pages: Tax (5/7)"
```

---

### Task 8: Household tab (Users + Activity Log, admin-only)

**Files:**
- Create: `frontend/src/pages/settings/HouseholdTab.tsx`
- Modify: `frontend/src/pages/Settings.tsx` (add the tab + route)

**Interfaces:**
- Consumes: `adminApi`, `authApi` from `../../api`; `isAdmin` from `../../store/auth`.
- Produces: nothing new consumed by later tasks.

- [ ] **Step 1: Create the Household tab**

Moves the Users section (old `Settings.tsx` lines 697-765) and Activity Log section (lines 767-833) verbatim, plus their state (lines 22, 81-88, 355-368), plus the Reset Password modal (1276-1313) and Add User modal (1396-1436). Both sections were already admin-gated (`{admin && (...)}`) -- keep that gate at the top of the component so a non-admin sees an empty tab body rather than the queries firing needlessly (matches today's behavior where `enabled: admin` already guards the queries).

```tsx
// frontend/src/pages/settings/HouseholdTab.tsx
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { adminApi, authApi } from "../../api";
import { isAdmin } from "../../store/auth";
import { Shield, Activity, User, Link, Plus, RotateCcw, Trash2, X } from "lucide-react";

const emptyUser = { username: "", display_name: "", password: "", role: "viewer", linked_to_user_id: "" };

export default function HouseholdTab() {
  const qc = useQueryClient();
  const admin = isAdmin();
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: authApi.me });
  const { data: users = [] } = useQuery<any[]>({ queryKey: ["admin-users"], queryFn: adminApi.listUsers, enabled: admin });
  const [logPage, setLogPage] = useState(0);
  const [logMethod, setLogMethod] = useState("");
  const { data: logData } = useQuery<any>({
    queryKey: ["audit-logs", logPage, logMethod],
    queryFn: () => adminApi.logs({ limit: 25, offset: logPage * 25, method: logMethod || undefined }),
    enabled: admin,
  });

  const [showUserForm, setShowUserForm] = useState(false);
  const [userForm, setUserForm] = useState({ ...emptyUser });
  const [resetPwUserId, setResetPwUserId] = useState<number | null>(null);
  const [resetPwValue, setResetPwValue] = useState("");
  const [resetPwError, setResetPwError] = useState<string | null>(null);
  const createUserMut = useMutation({ mutationFn: adminApi.createUser, onSuccess: () => { qc.invalidateQueries({ queryKey: ["admin-users"] }); setShowUserForm(false); setUserForm({ ...emptyUser }); } });
  const updateUserMut = useMutation({ mutationFn: ({ id, data }: any) => adminApi.updateUser(id, data), onSuccess: () => { qc.invalidateQueries({ queryKey: ["admin-users"] }); } });
  const removeUserMut = useMutation({ mutationFn: adminApi.removeUser, onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-users"] }) });
  const resetPwMut = useMutation({
    mutationFn: ({ id, pw }: { id: number; pw: string }) => adminApi.resetPassword(id, pw),
    onSuccess: () => { setResetPwUserId(null); setResetPwValue(""); setResetPwError(null); },
    onError: (e: any) => setResetPwError(e?.response?.data?.detail ?? "Failed to reset password"),
  });

  if (!admin) {
    return <div className="card"><p className="text-sm text-gray-500 dark:text-gray-400">Admin access required.</p></div>;
  }

  return (
    <div className="space-y-6">
      {/* ── Users ── */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100 flex items-center gap-2"><Shield size={16} className="text-indigo-500" /> Users</h3>
          <button onClick={() => setShowUserForm(true)} className="btn-primary btn-sm text-xs px-3 py-1.5"><Plus size={14} /> Add User</button>
        </div>
        <div className="divide-y divide-gray-100 dark:divide-gray-700">
          {users.map((u: any) => {
            const linkedTo = u.linked_to_user_id ? users.find((x: any) => x.id === u.linked_to_user_id) : null;
            return (
              <div key={u.id} className="py-3 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 bg-gray-100 dark:bg-gray-700 rounded-full flex items-center justify-center">
                    {linkedTo ? <Link size={14} className="text-indigo-500" /> : <User size={14} className="text-gray-500" />}
                  </div>
                  <div>
                    <p className="text-sm font-medium text-gray-900 dark:text-gray-100">{u.display_name}</p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">@{u.username}</p>
                    {linkedTo && (
                      <p className="text-xs text-indigo-500 dark:text-indigo-400">Linked to {linkedTo.display_name}'s data</p>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span className={`badge-${u.role === "admin" ? "blue" : "amber"}`}>{u.role}</span>
                  <button
                    onClick={() => updateUserMut.mutate({ id: u.id, data: { is_active: !u.is_active } })}
                    className={`text-xs px-2 py-1 rounded-md ${u.is_active ? "text-green-600 bg-green-50 dark:bg-green-900/20" : "text-gray-400 bg-gray-100 dark:bg-gray-700"}`}
                  >
                    {u.is_active ? "Active" : "Inactive"}
                  </button>
                  <select
                    className="input text-xs w-auto py-1"
                    value={u.role}
                    onChange={e => updateUserMut.mutate({ id: u.id, data: { role: e.target.value } })}
                  >
                    <option value="admin">Admin</option>
                    <option value="viewer">View Only</option>
                  </select>
                  <button
                    onClick={() => { setResetPwUserId(u.id); setResetPwValue(""); setResetPwError(null); }}
                    className="btn-ghost p-1.5 text-amber-500 hover:bg-amber-50 dark:hover:bg-amber-900/20"
                    title="Reset password"
                  >
                    <RotateCcw size={14} />
                  </button>
                  {u.id !== me?.id && (
                    <button
                      onClick={() => removeUserMut.mutate(u.id)}
                      className="btn-ghost p-1.5 text-red-400 hover:bg-red-50"
                      title="Remove user"
                    >
                      <Trash2 size={14} />
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Activity Log ── */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100 flex items-center gap-2"><Activity size={16} className="text-indigo-500" /> Activity Log</h3>
          <div className="flex items-center gap-2">
            <select className="input text-xs w-auto py-1" value={logMethod} onChange={e => { setLogMethod(e.target.value); setLogPage(0); }}>
              <option value="">All methods</option>
              <option value="POST">POST</option>
              <option value="PATCH">PATCH</option>
              <option value="DELETE">DELETE</option>
            </select>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-gray-100 dark:border-gray-700">
                <th className="text-left py-2 text-gray-500 font-medium pr-4">Time</th>
                <th className="text-left py-2 text-gray-500 font-medium pr-4">User</th>
                <th className="text-left py-2 text-gray-500 font-medium pr-4">Method</th>
                <th className="text-left py-2 text-gray-500 font-medium pr-4">Path</th>
                <th className="text-right py-2 text-gray-500 font-medium pr-4">Status</th>
                <th className="text-right py-2 text-gray-500 font-medium">ms</th>
              </tr>
            </thead>
            <tbody>
              {(logData?.items ?? []).map((log: any) => (
                <tr key={log.id} className="border-b border-gray-50 dark:border-gray-700/50 hover:bg-gray-50 dark:hover:bg-gray-700/30">
                  <td className="py-1.5 pr-4 text-gray-500 whitespace-nowrap">
                    {new Date(log.timestamp).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                  </td>
                  <td className="py-1.5 pr-4 text-gray-700 dark:text-gray-300">{log.username ?? "—"}</td>
                  <td className="py-1.5 pr-4">
                    <span className={`badge-${log.method === "DELETE" ? "red" : log.method === "PATCH" ? "amber" : "blue"}`}>{log.method}</span>
                  </td>
                  <td className="py-1.5 pr-4 text-gray-600 dark:text-gray-400 font-mono">{log.path}</td>
                  <td className="py-1.5 pr-4 text-right">
                    <span className={log.status_code < 300 ? "text-green-600" : log.status_code < 500 ? "text-amber-600" : "text-red-600"}>{log.status_code}</span>
                  </td>
                  <td className="py-1.5 text-right text-gray-500">{log.duration_ms}</td>
                </tr>
              ))}
              {(!logData?.items?.length) && (
                <tr><td colSpan={6} className="text-center py-6 text-gray-400">No activity yet</td></tr>
              )}
            </tbody>
          </table>
        </div>
        {logData && logData.total > 25 && (
          <div className="flex items-center justify-between mt-3 text-xs text-gray-500">
            <span>{logData.total} total entries</span>
            <div className="flex gap-2">
              <button onClick={() => setLogPage(p => Math.max(0, p - 1))} disabled={logPage === 0} className="btn-ghost px-2 py-1 text-xs disabled:opacity-40">← Prev</button>
              <span className="self-center">Page {logPage + 1}</span>
              <button onClick={() => setLogPage(p => p + 1)} disabled={(logPage + 1) * 25 >= logData.total} className="btn-ghost px-2 py-1 text-xs disabled:opacity-40">Next →</button>
            </div>
          </div>
        )}
      </div>

      {/* ── Reset Password modal ── */}
      {resetPwUserId !== null && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-sm">
            <div className="flex justify-between items-center mb-5">
              <h3 className="font-bold text-gray-900 dark:text-gray-100">Reset Password</h3>
              <button onClick={() => { setResetPwUserId(null); setResetPwValue(""); setResetPwError(null); }} className="btn-ghost p-1"><X size={18} /></button>
            </div>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
              Set a new password for <strong>{users.find((u: any) => u.id === resetPwUserId)?.display_name ?? "this user"}</strong>. They will be able to change it again after logging in.
            </p>
            <div className="space-y-3">
              <div>
                <label className="label">New Password</label>
                <input
                  type="password"
                  className="input"
                  value={resetPwValue}
                  onChange={e => setResetPwValue(e.target.value)}
                  placeholder="At least 6 characters"
                  autoFocus
                />
              </div>
              {resetPwError && <p className="text-sm text-red-600">{resetPwError}</p>}
              <div className="flex gap-3 pt-2">
                <button
                  onClick={() => resetPwMut.mutate({ id: resetPwUserId, pw: resetPwValue })}
                  disabled={resetPwMut.isPending || resetPwValue.length < 6}
                  className="btn-primary flex-1"
                >
                  {resetPwMut.isPending ? "Saving…" : "Set Password"}
                </button>
                <button onClick={() => { setResetPwUserId(null); setResetPwValue(""); setResetPwError(null); }} className="btn-secondary flex-1">Cancel</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Add User modal ── */}
      {showUserForm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-sm">
            <div className="flex justify-between items-center mb-5">
              <h3 className="font-bold text-gray-900 dark:text-gray-100">Add User</h3>
              <button onClick={() => setShowUserForm(false)} className="btn-ghost p-1"><X size={18} /></button>
            </div>
            <form onSubmit={e => {
              e.preventDefault();
              createUserMut.mutate({
                ...userForm,
                linked_to_user_id: userForm.linked_to_user_id ? parseInt(userForm.linked_to_user_id) : null,
              });
            }} className="space-y-3">
              <div><label className="label">Display Name</label><input className="input" placeholder="Jane Ford" value={userForm.display_name} onChange={e => setUserForm({ ...userForm, display_name: e.target.value })} required /></div>
              <div><label className="label">Username</label><input className="input" placeholder="janeford" value={userForm.username} onChange={e => setUserForm({ ...userForm, username: e.target.value })} required /></div>
              <div><label className="label">Password</label><input type="password" className="input" value={userForm.password} onChange={e => setUserForm({ ...userForm, password: e.target.value })} required /></div>
              <div>
                <label className="label">Access Level</label>
                <select className="input" value={userForm.role} onChange={e => setUserForm({ ...userForm, role: e.target.value })}>
                  <option value="viewer">View Only</option>
                  <option value="admin">Admin</option>
                </select>
              </div>
              <div>
                <label className="label">Link to Account (shared data access)</label>
                <select className="input" value={userForm.linked_to_user_id} onChange={e => setUserForm({ ...userForm, linked_to_user_id: e.target.value })}>
                  <option value="">Own account (standalone)</option>
                  <option value={String(me?.id)}>Link to my account ({me?.display_name})</option>
                </select>
                <p className="text-xs text-gray-400 mt-1">Linked users see the same financial data as your account.</p>
              </div>
              <div className="flex gap-3 pt-2">
                <button type="submit" className="btn-primary flex-1">Create User</button>
                <button type="button" onClick={() => setShowUserForm(false)} className="btn-secondary flex-1">Cancel</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add the tab to the shell**

In `frontend/src/pages/Settings.tsx`:

```tsx
import { Users as UsersIcon } from "lucide-react";
import HouseholdTab from "./settings/HouseholdTab";
```

```tsx
{ to: "household", label: "Household", icon: UsersIcon },
```

```tsx
<Route path="household" element={<HouseholdTab />} />
```

(Imported as `Users as UsersIcon` to avoid shadowing the `users` data variable naming convention used elsewhere in this codebase's Settings context -- not a real collision in this specific file since `Settings.tsx`'s shell has no `users` variable, but keep the alias for clarity/consistency.)

- [ ] **Step 3: Run tsc to verify**

Run: `cd frontend && npx tsc -b 2>&1 | grep -c "error TS"`
Expected: `11` (unchanged).

- [ ] **Step 4: Manual verification**

As an admin user, `/settings/household` shows Users (add/edit role/activate/deactivate/reset password/remove) and Activity Log (filter by method, pagination) with all existing functionality. As a non-admin, the tab still appears in the nav (matching today's behavior where the Settings page itself doesn't hide the tab structure) but its content shows "Admin access required."

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/settings/HouseholdTab.tsx frontend/src/pages/Settings.tsx
git commit -m "Split Settings into tabbed sub-pages: Household (6/7)"
```

---

### Task 9: Danger Zone tab + delete the legacy file's remaining scaffolding

**Files:**
- Create: `frontend/src/pages/settings/DangerZoneTab.tsx`
- Modify: `frontend/src/pages/Settings.tsx` (add the final tab + route; this is also where any leftover unused imports/scaffolding in the shell get cleaned up)

**Interfaces:**
- Consumes: `authApi`, `dataApi` from `../../api`.
- Produces: nothing (final tab).

- [ ] **Step 1: Create the Danger Zone tab**

Moves the Danger Zone section (old `Settings.tsx` lines 1086-1157) verbatim, plus its state (lines 327-353).

```tsx
// frontend/src/pages/settings/DangerZoneTab.tsx
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { authApi, dataApi } from "../../api";
import { clearAuth } from "../../store/auth";

export default function DangerZoneTab() {
  const qc = useQueryClient();

  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deletePassword, setDeletePassword] = useState("");
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const deleteAccountMut = useMutation({
    mutationFn: authApi.deleteAccount,
    onSuccess: () => { clearAuth(); window.location.href = "/login"; },
    onError: (e: any) => setDeleteError(e?.response?.data?.detail ?? "Failed to delete account"),
  });
  function handleDeleteAccount() { setDeleteError(null); deleteAccountMut.mutate({ password: deletePassword }); }

  const [clearConfirm, setClearConfirm] = useState<"transactions" | "cc-transactions" | null>(null);
  const clearTxnMut = useMutation({
    mutationFn: dataApi.clearTransactions,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["transactions"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
      setClearConfirm(null);
    },
  });
  const clearCCTxnMut = useMutation({
    mutationFn: dataApi.clearCCTransactions,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cc-transactions"] });
      qc.invalidateQueries({ queryKey: ["credit-cards"] });
      setClearConfirm(null);
    },
  });

  return (
    <div className="card border-red-100 dark:border-red-900/30">
      <h3 className="text-sm font-semibold text-red-600 dark:text-red-400 mb-3">Danger Zone</h3>
      <div className="space-y-4">

        {/* Clear checking transactions */}
        <div className="border border-red-100 dark:border-red-900/30 rounded-lg p-3 space-y-2">
          {clearConfirm !== "transactions" ? (
            <button onClick={() => { setClearConfirm("transactions"); setShowDeleteConfirm(false); }} className="text-sm text-red-600 hover:underline">
              Clear all checking transactions…
            </button>
          ) : (
            <div className="space-y-2">
              <p className="text-xs text-red-600">This permanently deletes all checking transactions and resets all account balances to $0. Your accounts, categories, and settings are kept.</p>
              <div className="flex gap-2">
                <button onClick={() => clearTxnMut.mutate()} disabled={clearTxnMut.isPending} className="bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white text-xs px-3 py-1.5 rounded-lg font-medium">
                  {clearTxnMut.isPending ? "Clearing…" : "Yes, clear transactions"}
                </button>
                <button onClick={() => setClearConfirm(null)} className="btn-secondary text-xs px-3">Cancel</button>
              </div>
            </div>
          )}
          <p className="text-xs text-gray-400">Keeps accounts, categories, recurring items, and rules.</p>
        </div>

        {/* Clear CC transactions */}
        <div className="border border-red-100 dark:border-red-900/30 rounded-lg p-3 space-y-2">
          {clearConfirm !== "cc-transactions" ? (
            <button onClick={() => { setClearConfirm("cc-transactions"); setShowDeleteConfirm(false); }} className="text-sm text-red-600 hover:underline">
              Clear all credit card transactions…
            </button>
          ) : (
            <div className="space-y-2">
              <p className="text-xs text-red-600">This permanently deletes all credit card transactions and resets all card balances to $0. Your cards, categories, and settings are kept.</p>
              <div className="flex gap-2">
                <button onClick={() => clearCCTxnMut.mutate()} disabled={clearCCTxnMut.isPending} className="bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white text-xs px-3 py-1.5 rounded-lg font-medium">
                  {clearCCTxnMut.isPending ? "Clearing…" : "Yes, clear CC transactions"}
                </button>
                <button onClick={() => setClearConfirm(null)} className="btn-secondary text-xs px-3">Cancel</button>
              </div>
            </div>
          )}
          <p className="text-xs text-gray-400">Keeps cards, categories, recurring items, and rules.</p>
        </div>

        {/* Delete entire account */}
        <div className="border border-red-100 dark:border-red-900/30 rounded-lg p-3 space-y-2">
        {!showDeleteConfirm ? (
          <button onClick={() => { setShowDeleteConfirm(true); setClearConfirm(null); }} className="text-sm text-red-600 hover:underline">
            Delete my account and all data…
          </button>
        ) : (
          <div className="space-y-2">
            <p className="text-xs text-red-600">This permanently deletes all your accounts, transactions, and settings. Enter your password to confirm.</p>
            <div className="flex flex-wrap items-center gap-2 max-w-sm">
              <input type="password" className="input text-sm flex-1 min-w-0" placeholder="Your password" value={deletePassword} onChange={e => setDeletePassword(e.target.value)} />
              <button onClick={handleDeleteAccount} disabled={deleteAccountMut.isPending || !deletePassword} className="bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white text-sm px-3 py-2 rounded-lg font-medium">
                {deleteAccountMut.isPending ? "Deleting…" : "Delete"}
              </button>
              <button onClick={() => { setShowDeleteConfirm(false); setDeletePassword(""); setDeleteError(null); }} className="btn-secondary text-sm px-3">Cancel</button>
            </div>
            {deleteError && <p className="text-xs text-red-600">{deleteError}</p>}
          </div>
        )}
        <p className="text-xs text-gray-400">Permanently removes your login, all accounts, and every piece of data.</p>
        </div>

      </div>
    </div>
  );
}
```

- [ ] **Step 2: Add the final tab to the shell**

In `frontend/src/pages/Settings.tsx`, the complete `TABS` array and route list should now read (this is the FULL final state of the shell -- read the current file first since it's grown across Tasks 2-8, then make it match this exactly):

```tsx
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { User, SlidersHorizontal, Link, Tags, Receipt, Users as UsersIcon, AlertTriangle } from "lucide-react";
import { cx } from "../lib/utils";
import ProfileTab from "./settings/ProfileTab";
import PreferencesTab from "./settings/PreferencesTab";
import AccountsTab from "./settings/AccountsTab";
import CategoriesTab from "./settings/CategoriesTab";
import TaxTab from "./settings/TaxTab";
import HouseholdTab from "./settings/HouseholdTab";
import DangerZoneTab from "./settings/DangerZoneTab";

const TABS = [
  { to: "profile", label: "Profile & Security", icon: User },
  { to: "preferences", label: "Preferences", icon: SlidersHorizontal },
  { to: "accounts", label: "Accounts & Bank Sync", icon: Link },
  { to: "categories", label: "Categories & Rules", icon: Tags },
  { to: "tax", label: "Tax", icon: Receipt },
  { to: "household", label: "Household", icon: UsersIcon },
  { to: "danger", label: "Danger Zone", icon: AlertTriangle, danger: true },
];

export default function Settings() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-gray-100">Settings</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400">Manage accounts, categories, and preferences</p>
      </div>
      <div className="flex flex-col md:flex-row gap-6">
        <nav className="md:w-48 shrink-0 flex md:flex-col gap-1 overflow-x-auto">
          {TABS.map(t => (
            <NavLink
              key={t.to}
              to={t.to}
              className={({ isActive }) =>
                cx(
                  "flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium whitespace-nowrap",
                  t.danger
                    ? (isActive ? "bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-400" : "text-red-500 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20")
                    : (isActive
                        ? "bg-indigo-50 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400"
                        : "text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700/50")
                )
              }
            >
              <t.icon size={16} />
              {t.label}
            </NavLink>
          ))}
        </nav>
        <div className="flex-1 min-w-0">
          <Routes>
            <Route index element={<Navigate to="profile" replace />} />
            <Route path="profile" element={<ProfileTab />} />
            <Route path="preferences" element={<PreferencesTab />} />
            <Route path="accounts" element={<AccountsTab />} />
            <Route path="categories" element={<CategoriesTab />} />
            <Route path="tax" element={<TaxTab />} />
            <Route path="household" element={<HouseholdTab />} />
            <Route path="danger" element={<DangerZoneTab />} />
          </Routes>
        </div>
      </div>
    </div>
  );
}
```

(This replaces whatever the `TABS` array/import list/`<Routes>` block has accumulated to after Tasks 2-8 -- the rest of the file outside those three spots hasn't changed since Task 2 Step 3 and shouldn't need touching.)

- [ ] **Step 3: Run tsc to verify**

Run: `cd frontend && npx tsc -b 2>&1 | grep -c "error TS"`
Expected: `11` (unchanged -- the drop to 11 already happened in Task 2 when the legacy monolith file was replaced; this task doesn't change the error count, just adds the final tab).

- [ ] **Step 4: Manual verification (full pass across the whole feature)**

With the dev server running:
- All 7 tabs render and switch correctly via the sub-nav; Danger Zone is visually red/distinct and sits last.
- `/settings` redirects to `/settings/profile`.
- Every form/mutation across all 7 tabs still works (spot-check at least one save action per tab).
- Sidebar (Task 1): pinned row + 3 groups + Settings render correctly; pin/unpin from the Preferences tab updates the sidebar live.
- Dashboard's "Add Account" button and Spending's tax-estimate "Go to Settings" link (Task 5) land on `/settings/accounts` and `/settings/tax` respectively.
- Reload the browser once: confirm no console errors, confirm `pinnedNav` persists.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/settings/DangerZoneTab.tsx frontend/src/pages/Settings.tsx
git commit -m "Split Settings into tabbed sub-pages: Danger Zone (7/7) -- refactor complete

All 7 tabs now live under settings/, each its own file. Settings.tsx
is a ~50-line shell (tab nav + nested routes). tsc baseline is 11
(down from 13 at the start of this plan -- both pre-existing bugs that
lived in the old monolithic file are gone, see Global Constraints)."
```

---

## Global verification (after all tasks)

```bash
cd frontend && npx tsc -b 2>&1 | grep -c "error TS"
```

Expected: `11` (down from the 13 pre-existing baseline at the start of this plan -- two bugs native to the old `Settings.tsx` are gone as a side effect of the refactor, see Global Constraints).

No backend changes in this plan, so the backend test suite is unaffected -- running it is optional but harmless (`cd backend && source ../.venv/bin/activate && python -m pytest -q`) if you want a final sanity check that nothing cross-cutting broke.
