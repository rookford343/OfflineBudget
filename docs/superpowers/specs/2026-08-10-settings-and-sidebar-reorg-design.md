# Settings & Sidebar Reorganization — Design

**Status:** Approved by Dan 2026-08-10 (verbal, via brainstorming session).

## Problem

Two related IA problems, both flagged early in the OfflineBudget rebuild and deferred until now:

1. **Settings is one 1439-line page** (`frontend/src/pages/Settings.tsx`) with ~13 sections stacked in a single scroll: Preferences, Accounts, Bank Connections, Categories, Transaction Rules, Users, Activity Log, Profile, Email Notifications, Recovery Code, Tax Profile, Change Password, Danger Zone. Finding any one setting means scrolling past a dozen unrelated ones.
2. **The sidebar is 12 flat items** (`frontend/src/components/Layout.tsx`) with no grouping — Dashboard, Goals, Net Worth, Calendar, Credit Cards, Forecast, Spending, Recurring, Transactions, Import, Budget, Settings — in a single undifferentiated column.

## Decisions (from brainstorming)

- **Settings → tabbed sub-pages**, not accordions or fewer-but-still-long pages. Each tab is its own screen; no more scrolling past 12 other things to find one setting.
- **Sidebar → grouped sections** (not collapsible, not a flat reorder) with a **pinned favorites row** above the groups for quick access to a user's most-used pages.
- **Favorites are chosen via Settings toggles**, not drag-and-drop. This **replaces** the existing drag-to-reorder sidebar (`navOrder` in localStorage, up/down arrow buttons in Settings, `nav-order-changed` event) entirely — one mechanism, not two.
- **Dashboard is permanently pinned** — not a togglable favorite, always present, cannot be unpinned. Every other item is opt-in.
- Dan's own first pick beyond Dashboard: **Forecast**.

## Sidebar Architecture

### Structure (top to bottom)

```
┌─────────────────────┐
│ OfflineBudget        │
│ Dan                   │
├─────────────────────┤
│ ★ Dashboard  (locked) │  <- pinned row, always Dashboard + user's other picks
│ ★ Forecast            │
├─────────────────────┤
│ OVERVIEW              │
│   Net Worth            │
│   Calendar              │
├─────────────────────┤
│ MONEY                 │
│   Transactions          │
│   Spending               │
│   Recurring               │
│   Import                   │
├─────────────────────┤
│ PLANNING               │
│   Budget                 │
│   Goals                    │
│   Credit Cards               │
├─────────────────────┤
│ Settings               │  <- always last, ungrouped
└─────────────────────┘
```

If an item is pinned, it appears ONLY in the pinned row, not also in its group (no duplication). Dashboard never appears in a group at all — it's not a member of Overview/Money/Planning, only ever the pinned row.

### Groups (fixed, not user-editable in this iteration — YAGNI: nobody asked to rename or restructure groups, only to pin favorites)

- **Overview:** Net Worth, Calendar
- **Money:** Transactions, Spending, Recurring, Import
- **Planning:** Budget, Goals, Credit Cards, Forecast. Forecast is a member of Planning by default; once Dan pins it (per his stated first pick), the no-duplication rule above moves it out of Planning entirely — it then renders only in the pinned row, not in both places.

### Data model

Replace `navOrder` (full 12-item order array) with `pinnedNav`: a `string[]` of `to` paths the user has pinned, persisted the same way (`localStorage`, key `pinnedNav`), broadcast the same way (reuse the `nav-order-changed` event name so no other integration point changes). `"/dashboard"` is always implicitly included — it's not stored in `pinnedNav` at all (storing it would let it be accidentally removed by a bug in list-manipulation code; keeping it structurally separate makes "always present" a type-level guarantee, not a runtime check every render).

```ts
function loadPinnedNav(): string[] {
  try {
    const saved = localStorage.getItem("pinnedNav");
    return saved ? JSON.parse(saved) : [];
  } catch { return []; }
}
// Rendered pinned row = [dashboardItem, ...pinnedNav.map(lookup)]
```

### Mobile bottom-nav

Today: `orderedNav.slice(0, 5)`. After: the pinned row itself (Dashboard + favorites), capped at 5 — if Dan pins more than 4 extra items, the bottom nav shows the first 4 in pinned-list order plus Dashboard; the full pinned row (no cap) still renders in the desktop sidebar. Getting a 6th mobile slot is not a requirement here (YAGNI) — if it becomes one, the cap is one line to change.

### Migration

On first load after this ships, if `localStorage.navOrder` exists and `localStorage.pinnedNav` does not, seed `pinnedNav` from `navOrder`'s first 4 non-dashboard entries (best-effort continuity with whatever a user had already customized) and delete `navOrder`. If a user never touched drag-order, `pinnedNav` starts empty and they see just Dashboard pinned — matches every other user's fresh-install experience, so nothing decides FOR them.

## Settings Architecture

### Tabs

Route structure: `/settings/:tab`, defaulting `/settings` → redirect to `/settings/profile`.

| Tab (route) | Contains (today's section names) |
|---|---|
| `profile` | Profile, Email Notifications, Recovery Code, Change Password |
| `preferences` | Preferences (existing), **new:** Pinned sidebar items picker |
| `accounts` | Accounts, Bank Connections |
| `categories` | Categories, Transaction Rules |
| `tax` | Tax Profile |
| `household` | Users, Activity Log |
| `danger` | Danger Zone |

Tab order in the sub-nav matches the table above, with Danger Zone visually separated (red accent, like today) even though it's still just a tab, not a modal-gated special case.

### New: Pinned sidebar items picker (Preferences tab)

A checklist of every non-Dashboard nav item (the same 11-item list `ALL_NAV_ITEMS` already enumerates in Settings.tsx today, minus Dashboard). Checking an item adds it to `pinnedNav`; unchecking removes it. No ordering control in this iteration (YAGNI — Dan asked for quick access, not a second drag-reorder system; pinned items render in a fixed order matching `ALL_NAV_ITEMS`'s existing sequence). Writes straight to `localStorage` + dispatches `nav-order-changed`, same pattern the old reorder buttons used.

### Component split

`Settings.tsx` (1439 lines today) becomes a thin shell: renders the tab sub-nav and an `<Outlet />`-style switch (react-router nested routes, matching how `Layout.tsx` already nests page routes under itself). Each tab's content, state, queries, and mutations move into their own file under a new `frontend/src/pages/settings/` directory:

- `frontend/src/pages/Settings.tsx` — shell: tab nav + route switch
- `frontend/src/pages/settings/ProfileTab.tsx`
- `frontend/src/pages/settings/PreferencesTab.tsx` (includes the new pinned-items picker)
- `frontend/src/pages/settings/AccountsTab.tsx`
- `frontend/src/pages/settings/CategoriesTab.tsx`
- `frontend/src/pages/settings/TaxTab.tsx`
- `frontend/src/pages/settings/HouseholdTab.tsx`
- `frontend/src/pages/settings/DangerZoneTab.tsx`

Shared bits used by more than one tab (e.g. any common modal styling, the `ALL_NAV_ITEMS` list itself) move to a small `frontend/src/pages/settings/shared.ts` rather than being duplicated or left in the shell for others to import from (importing "sideways" from a sibling tab file would recreate exactly the tangled-file problem this split exists to fix).

### Deep-link updates

Two existing links currently point at bare `/settings` and should point at the specific tab instead, now that tabs exist:
- `Spending.tsx`'s tax-estimate error link → `/settings/tax`
- `Dashboard.tsx`'s "Add Account" button → `/settings/accounts`

## Testing

Frontend-only change (no backend routes, no new API surface — `pinnedNav` is pure client-side localStorage state, same as today's `navOrder`). No existing backend test coverage is affected. Verification is via `tsc -b` (must stay at the current 13-error baseline, 0 new) and Interceptor visual verification of: sidebar renders pinned row + groups correctly, pin/unpin toggles work and persist across reload, each Settings tab renders its moved content, the two updated deep-links land on the right tab, and the `navOrder` → `pinnedNav` migration runs once and doesn't re-run on a second reload.

## Out of scope

- Editable/renameable groups, or letting the user reorder groups themselves (YAGNI — nobody asked).
- Ordering control within the pinned row (YAGNI — same).
- Backend persistence of sidebar/settings preferences (stays client-side localStorage, matching today's `navOrder`; if Dan ever wants this to follow him across devices, that's a real feature request for a future spec, not implied by this one).
- Any change to what each individual Settings section/page actually does — this is purely a reorganization of where things live, not a rewrite of their behavior.
