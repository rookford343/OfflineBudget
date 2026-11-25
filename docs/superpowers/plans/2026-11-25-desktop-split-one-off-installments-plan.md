# Desktop Split One-Off Installments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Forecast page's inline "Add" one-off form (the one Dan actually uses on desktop) the same "split into separate payments" capability the phone sheet already ships, including a live combined Safety Margin preview, without touching the backend, the phone sheet, editing, or delete/cancel.

**Architecture:** The split-installments backend (`POST /planned-expenses/installments`, `POST /planned-expenses/installments/preview`) and the pure `splitEvenly` helper already exist and are already proven correct — they were built and shipped for `PlanOneOffSheet.tsx` on 2026-11-21. This plan ports the same client-side pattern (split toggle → total/count/even-split → per-leg rows → debounced preview query → gated submit) into `Forecast.tsx`'s existing inline add form, reusing its existing state/mutation conventions rather than the phone sheet's. No new files, no shared extraction between the two components — the duplicated ~15 lines of leg-state plumbing is cheaper than a shared abstraction for two call sites.

**Tech Stack:** React + TypeScript, `@tanstack/react-query`. `bun` for the frontend toolchain (never npm/npx).

**Spec:** No separate design doc for this plan — it is a direct port of already-approved, already-shipped behavior from `docs/superpowers/specs/2026-11-20-split-one-off-installments-design.md` into a second UI surface. That design doc is the authority for backend behavior (unchanged here); this plan is the authority for how it reaches the desktop Forecast form.

## Why This Plan Exists

The original feature was built only into `frontend/src/components/phone/PlanOneOffSheet.tsx`, reached from `Dashboard.tsx` only when `useMinWidth(1024)` is false. On a real desktop window, `Dashboard.tsx` (line 277) branches away from that sheet entirely, and Dashboard's desktop view exposes no one-off creation UI at all. The one-off creation Dan actually uses lives entirely on the Forecast page, in a separate, older inline form (`frontend/src/pages/Forecast.tsx`, the `showExpenseForm` block around lines 1022-1111) that has no concept of installments. This plan closes that gap.

## Global Constraints

- Installments are **always outflow** — `PlannedExpenseInstallmentsCreate` (`backend/schemas.py:1965`) has no `direction` field. The Direction selector must be hidden entirely when split mode is on, not merely disabled.
- Funding fields are **excluded from split installments by backend design** (`PlannedExpenseInstallmentsCreate` has no funding fields at all — see its docstring at `backend/schemas.py:1966-1969`). The "Fund from" block must be hidden entirely when split mode is on. This is unchanged from the phone sheet and is not up for reconsideration in this task.
- Editing an existing leg (including giving it a funding source after the fact) already works today via the unchanged `PATCH /{expense_id}` endpoint and `Forecast.tsx`'s existing per-row edit form (lines ~864-937) — **do not touch the edit form.**
- Delete/cancel already warns correctly for grouped legs via the existing `ConfirmDialog` at `Forecast.tsx:1415-1427` — **do not touch it.**
- Cap is 2-6 legs, enforced server-side already (`installment_plan.MIN_INSTALLMENTS`/`MAX_INSTALLMENTS`); mirror it client-side with disabled stepper buttons at the bounds, exactly like the phone sheet does.
- Query-invalidation on success must match this file's existing convention **exactly** — only `["planned-expenses"]`, `["forecast-quarters"]`, `["forecast-multi-year"]` (the same three keys `createExpenseMut`, `deleteExpenseMut`, and `updateExpenseMut` already use at `Forecast.tsx:321-365`). Do **not** import the phone sheet's broader `invalidateAndClose` list (`budget-snapshot`, `weekly-digest`, etc.) — that is a different component's convention, not this file's.
- This repo has **no page/component-level frontend tests anywhere** (`frontend/src/**/*.test.ts(x)` only covers pure-logic helpers in `lib/`; neither `Forecast.tsx` nor `PlanOneOffSheet.tsx` has one). Do not invent a new component-test harness for this task — that is disproportionate scope for a UI port. Verification is: `bunx vite build` succeeds (type-checks the new code), the existing `bun test` suite stays green, and a live walkthrough (Interceptor, or Dan doing it by hand if Interceptor is unavailable).
- No backend changes. No changes to `splitEvenly.ts`, its test, `PlanOneOffSheet.tsx`, or the `plannedExpensesApi` client (`previewInstallments`/`createInstallments` already exist and are already used elsewhere).

## Review Focus

- Toggling split mode off after partially filling legs must not leave stale state that gets silently submitted through the other mutation, and must not leave a stale error message from one mutation showing after switching to the other mode (the phone sheet hit exactly this bug and fixed it by calling `.reset()` on both mutations on toggle — see commit `3b67f03`).
- The Payments stepper must clamp to [2,6] and growing/shrinking the leg count must preserve already-entered amounts/dates for the legs that remain, not wipe the whole array (mirror `PlanOneOffSheet.tsx`'s `changeCount`).
- "Split evenly" must require a positive Total before it's clickable, and must overwrite only leg amounts, preserving any dates already typed per leg (mirror `handleSplitEvenly`'s `legs[i]?.expected_date ?? ""`).
- The Add button must stay disabled until the preview actually reflects the current form contents (a `previewMatchesForm` check comparing the live draft to the debounced one) — without it, a user could submit while a stale preview is still on screen.
- Switching "Charge to" between a specific checking account, a card, and "Any checking account" must correctly re-resolve the account the preview is computed against (falling back to the page's own active checking account for a card or "any" selection, never previewing against `undefined`), and must re-trigger the preview query.

---

### Task 1: Add split-into-installments mode to Forecast.tsx's inline one-off creation form

**Files:**
- Modify: `frontend/src/pages/Forecast.tsx`

**Interfaces:**
- Consumes (already exist, unchanged):
  - `plannedExpensesApi.previewInstallments(accountId: number, data: object) => Promise<InstallmentsPreviewOut>` (`frontend/src/api/index.ts:328`) — returns `{ safety_margin_weekly: { before, after }, safety_margin: { before, after }, card_payments: [{ card_id, due, amount }] }`.
  - `plannedExpensesApi.createInstallments(data: object) => Promise<PlannedExpenseOut[]>` (`frontend/src/api/index.ts:330`).
  - `splitEvenly(totalDollars: number, count: number): number[]` (`frontend/src/lib/splitEvenly.ts`).
  - `useDebouncedValue<T>(value: T, delayMs: number): T` (`frontend/src/lib/useDebouncedValue.ts`) — already used elsewhere in the app, not yet imported in `Forecast.tsx`.
  - `keepPreviousData` from `@tanstack/react-query` — not yet imported in `Forecast.tsx`.
- Produces: nothing new consumed elsewhere — this form's state is local to the component.

- [ ] **Step 1: Add new imports**

  In `frontend/src/pages/Forecast.tsx`, add `keepPreviousData` to the existing `@tanstack/react-query` import (line 2), add `fmtDate` to the existing `"../lib/utils"` import (line 4), and add two new import lines near the other `lib` imports:
  ```ts
  import { useDebouncedValue } from "../lib/useDebouncedValue";
  import { splitEvenly } from "../lib/splitEvenly";
  ```

- [ ] **Step 2: Add local leg type and helper, and new component state**

  Near the top of the file, alongside the existing `emptyExpense` constant (line 37), add:
  ```ts
  type ExpenseLeg = { amount: string; expected_date: string };
  const emptyExpenseLegs = (n: number): ExpenseLeg[] =>
    Array.from({ length: n }, () => ({ amount: "", expected_date: "" }));
  ```

  Inside the component, alongside the existing `showExpenseForm`/`expenseForm` state (after line 100), add:
  ```ts
  const [splitExpense, setSplitExpense] = useState(false);
  const [expenseTotal, setExpenseTotal] = useState("");
  const [expenseLegCount, setExpenseLegCount] = useState(2);
  const [expenseLegs, setExpenseLegs] = useState<ExpenseLeg[]>(emptyExpenseLegs(2));
  ```

- [ ] **Step 3: Add a combined reset helper and wire it into Cancel/X and both mutations' success handlers**

  Add a function (near the existing mutations, e.g. just above `createExpenseMut`):
  ```ts
  const resetExpenseAddForm = () => {
    setExpenseForm({ ...emptyExpense });
    setSplitExpense(false);
    setExpenseTotal("");
    setExpenseLegCount(2);
    setExpenseLegs(emptyExpenseLegs(2));
  };
  ```
  Replace the existing `setExpenseForm({ ...emptyExpense });` inside `createExpenseMut`'s `onSuccess` (line 329) with a call to `resetExpenseAddForm()`. Replace both `onClick={() => setShowExpenseForm(false)}` handlers in the add-form block (the X button at line 1026 and the Cancel button at line 1107) with a handler that calls `setShowExpenseForm(false)` and then `resetExpenseAddForm()`.

- [ ] **Step 4: Add the split-mode toggle and stale-error reset**

  Immediately after the Name field inside the `{showExpenseForm && (...)}` block (after line 1032), add a checkbox row matching this file's existing label/input conventions (not the phone sheet's touch-target sizing):
  ```tsx
  <div className="col-span-2 flex items-center gap-2">
    <input
      id="expense-split"
      type="checkbox"
      className="h-4 w-4"
      checked={splitExpense}
      onChange={(e) => {
        setSplitExpense(e.target.checked);
        // Each mode only ever submits through its own mutation -- without this,
        // a stale isError from the mode just left would show "Couldn't add
        // it" for a submit that never happened in the newly-selected mode.
        createExpenseMut.reset();
        createInstallmentsMut.reset();
      }}
    />
    <label htmlFor="expense-split" className="text-sm text-gray-700 dark:text-gray-300">
      Split into separate payments
    </label>
  </div>
  ```

- [ ] **Step 5: Replace the Amount/Expected Date fields with a mode-conditional block**

  Wrap the existing Amount + Expected Date grid pair (lines 1033-1040) in `{!splitExpense && (...)}`. Immediately after it, add the split-mode block, `{splitExpense && (...)}`, following `PlanOneOffSheet.tsx`'s structure (lines 220-279) adapted to this file's `grid grid-cols-2 gap-3` / `label`/`input` classes instead of the sheet's `min-h-[44px]` touch sizing:
  - A `Total` number input (bound to `expenseTotal`) and a `Payments` stepper (bound to `expenseLegCount`, buttons disabled at `<= 2` / `>= 6`) side by side.
  - A full-width "Split evenly" button, disabled unless `parseFloat(expenseTotal) > 0`, that computes `splitEvenly(parseFloat(expenseTotal), expenseLegCount)` and writes the results into `expenseLegs` amounts while preserving each leg's existing `expected_date` (mirror `handleSplitEvenly`).
  - One `amount`/`expected_date` input pair per entry in `expenseLegs`, labeled "Payment N amount" / "Payment N date", each updating only its own leg on change (mirror `updateLeg`).

  The stepper's count-change handler must slice/extend `expenseLegs` to the new length without discarding already-entered legs (mirror `changeCount`):
  ```ts
  const changeExpenseLegCount = (delta: number) => {
    const next = Math.min(6, Math.max(2, expenseLegCount + delta));
    setExpenseLegCount(next);
    setExpenseLegs((prev) => {
      const trimmed = prev.slice(0, next);
      return trimmed.length < next ? [...trimmed, ...emptyExpenseLegs(next - trimmed.length)] : trimmed;
    });
  };
  ```

- [ ] **Step 6: Hide Direction and Fund-from in split mode**

  Wrap the existing Direction field (lines 1041-1047) in `{!splitExpense && (...)}`. Wrap the existing "Fund from (optional)" `col-span-2` block (lines 1066-1094) in `{!splitExpense && (...)}`. The "Charge to" field (lines 1048-1065) and Notes field (lines 1095-1098) are unchanged and shared by both modes.

- [ ] **Step 7: Add the debounced installments preview query**

  Add, alongside the existing form state:
  ```ts
  const installmentsDraft = useMemo(() => ({
    name: expenseForm.name.trim() || "One-off",
    legs: expenseLegs.map((l) => ({ amount: l.amount, expected_date: l.expected_date })),
    account_id: expenseForm.account_id ? parseInt(expenseForm.account_id) : null,
    card_id: expenseForm.card_id ? parseInt(expenseForm.card_id) : null,
  }), [expenseForm.name, expenseLegs, expenseForm.account_id, expenseForm.card_id]);
  const debouncedInstallmentsDraft = useDebouncedValue(installmentsDraft, 300);
  const expenseLegsReady = expenseLegs.length >= 2 && expenseLegs.every((l) => parseFloat(l.amount) > 0 && !!l.expected_date);
  // The account the money leaves: the chosen checking account, or -- for a
  // card or "Any checking account" -- this page's own active checking account.
  const installmentsPreviewAccountId = expenseForm.account_id ? parseInt(expenseForm.account_id) : activeAccountId;

  const {
    data: installmentsPreview,
    isFetching: installmentsPreviewFetching,
    isError: installmentsPreviewIsError,
    isPlaceholderData: installmentsPreviewIsStale,
  } = useQuery<any>({
    queryKey: ["one-off-preview-installments", installmentsPreviewAccountId, debouncedInstallmentsDraft],
    queryFn: () => plannedExpensesApi.previewInstallments(installmentsPreviewAccountId, debouncedInstallmentsDraft),
    enabled: showExpenseForm && splitExpense && expenseLegsReady && !!installmentsPreviewAccountId,
    staleTime: 0,
    gcTime: 0,
    placeholderData: keepPreviousData,
  });
  const installmentsPreviewMatchesForm = JSON.stringify(installmentsDraft) === JSON.stringify(debouncedInstallmentsDraft);
  ```
  `useMemo` must be imported from `"react"` alongside the existing `useEffect, useRef, useState` import (line 1) if not already present.

- [ ] **Step 8: Add the createInstallments mutation**

  Alongside `createExpenseMut` (after line 330):
  ```ts
  const createInstallmentsMut = useMutation({
    mutationFn: (body: object) => plannedExpensesApi.createInstallments(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["planned-expenses"] });
      qc.invalidateQueries({ queryKey: ["forecast-quarters"] });
      qc.invalidateQueries({ queryKey: ["forecast-multi-year"] });
      setShowExpenseForm(false);
      resetExpenseAddForm();
    },
  });
  ```

- [ ] **Step 9: Render the preview panel and wire the submit button**

  Immediately before the existing error line / submit buttons (line 1099), add, visible only in split mode:
  ```tsx
  {splitExpense && (
    <div className="col-span-2 rounded-xl bg-gray-50 dark:bg-[#333947] p-3" aria-live="polite">
      {!expenseLegsReady && <p className="text-sm text-gray-500 dark:text-gray-400">Enter at least 2 payments with an amount and a date to see the effect.</p>}
      {expenseLegsReady && installmentsPreviewIsError && <p className="text-sm text-red-600 dark:text-red-400">Couldn't work out the preview. Try again.</p>}
      {expenseLegsReady && !installmentsPreviewIsError && !installmentsPreview && <p className="text-sm text-gray-500 dark:text-gray-400">Working it out…</p>}
      {expenseLegsReady && installmentsPreview && (
        <div className={installmentsPreviewFetching ? "opacity-60" : ""}>
          <p className="text-xs font-medium text-gray-500 dark:text-gray-400">Safety Margin (this week)</p>
          <p className="text-2xl font-bold tabular-nums text-gray-900 dark:text-gray-100">
            {fmt(installmentsPreview.safety_margin_weekly.before)} → {fmt(installmentsPreview.safety_margin_weekly.after)}
          </p>
          <p className="text-sm text-gray-600 dark:text-gray-300">
            This month: {fmt(installmentsPreview.safety_margin.before)} → {fmt(installmentsPreview.safety_margin.after)}
          </p>
          {installmentsPreview.card_payments?.map((cp: { card_id: number; due: string; amount: number | string }, i: number) => (
            <p key={i} className="mt-1 text-sm text-gray-600 dark:text-gray-300">
              Adds {fmt(cp.amount)} to {activeCards.find((c: any) => c.id === cp.card_id)?.name ?? "the card"} payment due {fmtDate(cp.due)}
            </p>
          ))}
        </div>
      )}
    </div>
  )}
  ```
  Then update the existing submit button block (lines 1099-1108):
  - Error line: change the condition to `{(createExpenseMut.isError || createInstallmentsMut.isError) && <p className="...">Couldn't add it. Try again.</p>}` (reuse this file's existing error-text styling; there is currently no such line in the non-split path, so add one consistent with the phone sheet's wording).
  - Submit button `onClick`: `() => splitExpense ? createInstallmentsMut.mutate(debouncedInstallmentsDraft) : createExpenseMut.mutate({ ...existing non-split payload... })`.
  - Submit button `disabled`: `splitExpense ? !(expenseLegsReady && installmentsPreviewMatchesForm && !!installmentsPreview && !installmentsPreviewFetching && !installmentsPreviewIsStale && !installmentsPreviewIsError && !createInstallmentsMut.isPending) : (!expenseForm.name || !expenseForm.amount || createExpenseMut.isPending)`.
  - Button label: `(createExpenseMut.isPending || createInstallmentsMut.isPending) ? "Saving…" : "Add Planned Expense"`.

- [ ] **Step 10: Type-check and build**

  Run: `cd frontend && bunx vite build`
  Expected: builds clean, no new TypeScript errors beyond the 35 pre-existing tracked ones (confirm the count hasn't grown by diffing `tsc -b` output against `main` if in doubt).

- [ ] **Step 11: Run the existing frontend test suite**

  Run: `cd frontend && bun test`
  Expected: all existing tests still pass (77 passed as of the last pre-push run) — this task adds no new test files per the Global Constraints note on this repo's test conventions.

- [ ] **Step 12: Commit**

  ```bash
  git add frontend/src/pages/Forecast.tsx
  git commit -m "Add split-into-installments mode to the desktop one-off form"
  ```
