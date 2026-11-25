# Split Off Already-Paid Portion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Dan take an existing, ordinary (single, ungrouped) one-off `PlannedExpense` and record that part of it has already been paid in real life, splitting it into a settled history leg (the real amount, the real date) and a shrunk remaining-balance leg that stays on the original due date -- without touching the backend's bulk 2-6-leg split-creation flow, which is a separate, forward-only capability.

**Architecture:** One new backend service function in `backend/services/installment_plan.py` reuses this feature's existing `installment_group_id` self-reference and "(k of N)" naming convention, so the already-shipped delete/cancel cascade (`cancel_installment_group`, `_retarget_group`, `_refund_watches`) works on the result with zero changes. One new endpoint on the existing `planned_expenses` router. One new UI affordance inside `Forecast.tsx`'s existing per-row edit form -- the only place in the app a one-off gets edited (confirmed this session: `PlanOneOffSheet.tsx` is create-only, and Dashboard's desktop view exposes no one-off editing at all).

**Tech Stack:** FastAPI + SQLAlchemy + SQLite (backend), React + TypeScript (frontend, `bun`, never npm).

**Spec:** No separate design doc -- this is a narrower, simpler capability than a full written design warrants, brainstormed and fully settled in chat with Dan on 2026-11-25 (see that conversation for the full reasoning trail). The concrete motivating case, confirmed against live production data: "Leia Dental Cleaning", a single $620.00 outflow via Chase Sapphire due 2026-12-21, with $292.00 of it already charged to that card on 2026-11-22 -- Dan wants that reflected as a $292.00 settled leg plus a $328.00 still-forecasted leg on the original due date.

## Global Constraints

- This is explicitly **not** the general N-leg retroactive splitter Dan considered and declined -- it produces exactly 2 legs: the paid portion and the remaining balance. An expense that's already part of a group (`installment_group_id is not None`) is out of scope; reject it with a 422, don't try to extend an existing group.
- The paid-portion amount must be strictly less than the original's total amount. Equal-or-more means the whole thing is paid -- that's the existing `settle` flow's job (`POST /planned-expenses/{id}/settle`, already shipped, unchanged), not this one. Reject with a 422 naming that endpoint.
- The anchor convention this feature already uses everywhere else is "the lowest id in the group." The existing single expense's id is always lower than the new leg's id (new rows get higher ids), so the **existing row stays the anchor** (`installment_group_id = expense.id` on both legs) -- there is no id-reassignment step like `create_installment_group`'s `legs[0].id` dance, because the anchor already exists.
- Naming mirrors `create_installment_group`'s exact format, `f"{name} ({i} of {n})"`, with the paid leg as `(1 of 2)` and the remaining balance as `(2 of 2)` -- deposit-first ordering, matching how Dan described the real case, regardless of either leg's actual date.
- The new paid leg is created with `settled_on` and `actual_amount` both set (to `date_paid`/`amount_paid`), which is exactly `_is_cleared()`'s definition (`backend/services/installment_plan.py:147-148`) -- so it already composes correctly with the unmodified `cancel_installment_group` if either leg is later deleted. Do not special-case this anywhere else.
- Funding fields (`funding_account_id`/`funding_amount`/`funding_lead_days`) must end up null/`0` on the remaining leg even if the original single expense had them set, and must never be set on the new paid leg -- this feature's existing invariant is that **no grouped leg ever carries funding fields** (see the design doc this feature shipped from), and this is the one path that could otherwise violate it by grouping a row that pre-dates that invariant.
- `direction` on the new paid leg copies the original's `direction` unchanged (do **not** force `outflow` -- unlike `create_installment_group`'s brand-new legs, this one mirrors an existing single entry that could in principle be either direction).
- Service functions in this file flush only; the caller (router) commits -- same convention as every other function in `installment_plan.py`. Business-rule rejections (already grouped, amount too large) belong in the router as `HTTPException(422, ...)`, before the service function is called, matching this router's existing pattern (see `adventures.py` for the house style, `planned_expenses.py` for the 404-ownership pattern already in use here).
- No change to `create_installment_group`, `preview_installment_group`, `cancel_installment_group`, `_retarget_group`, `_refund_watches`, `retarget_before_deleting_refund_watch`, the delete endpoint's branching, `PlanOneOffSheet.tsx`, or the Forecast page's existing per-row edit fields.
- This repo has no page/component-level frontend tests (only pure-logic `lib/` helpers have `.test.ts` files) -- the frontend task's verification is `bunx vite build` + `bun test` staying green, same as the desktop-split-installments task earlier today. Backend gets real pytest coverage as usual.

## Review Focus

- Using this action on an expense that already has `installment_group_id` set must be rejected (422), not silently create a nonsensical nested group.
- Amount-paid equal to or greater than the total must be rejected (422) rather than producing a zero or negative remaining leg.
- The remaining leg's `funding_account_id`/`funding_amount`/`funding_lead_days` must come out null/`0` even when the original expense had funding set before this action ran -- the one case where this feature's "grouped legs never fund" invariant could otherwise be silently broken.
- Deleting the new paid leg afterward (via the existing, unmodified delete endpoint) must correctly open a refund-watch for it and leave the remaining leg alone -- a live composition check against `cancel_installment_group`'s unmodified cascade logic, not a new code path, but worth proving explicitly since this is the first time a leg created outside `create_installment_group` enters that cascade.
- The two legs' amounts must sum to exactly the original total (Decimal arithmetic, no float-rounding drift) -- this is a money app; a one-cent discrepancy between what was forecasted and what the two legs now show would be a silent, hard-to-notice correctness bug.

---

### Task 1: Backend -- split-off-paid-portion service function and endpoint

**Files:**
- Modify: `backend/schemas.py` (new input schema)
- Modify: `backend/services/installment_plan.py` (new service function)
- Modify: `backend/routers/planned_expenses.py` (new endpoint)
- Test: `backend/tests/test_split_off_paid_portion.py` (new)

**Interfaces:**
- Consumes: `models.PlannedExpense`, `_is_cleared()` (`backend/services/installment_plan.py:147`, already defined, do not redefine), `cancel_installment_group` (exercised indirectly by Step 7's test, not called directly by this task's own code).
- Produces: `split_off_paid_portion(db: Session, user: models.User, expense: models.PlannedExpense, amount_paid: Decimal, date_paid: date) -> list[models.PlannedExpense]` -- returns `[paid_leg, expense]` in that order, both already flushed with real ids. `schemas.PlannedExpensePartialPaidIn(amount_paid: Decimal, date_paid: date)`. Endpoint `POST /planned-expenses/{expense_id}/already-paid`, response model `schemas.PlannedExpenseInstallmentsOut` (already defined at `backend/schemas.py:1990-1991`, reused as-is -- it's just `{legs: list[PlannedExpenseOut]}`).

- [ ] **Step 1: Add the input schema**

  In `backend/schemas.py`, alongside `InstallmentLegIn` (around line 1954), add:
  ```python
  class PlannedExpensePartialPaidIn(BaseModel):
      amount_paid: Decimal
      date_paid: date

      @model_validator(mode="after")
      def _amount_paid_is_positive(self):
          if self.amount_paid <= 0:
              raise ValueError("amount paid must be greater than zero")
          return self
  ```

- [ ] **Step 2: Write the failing tests**

  In `backend/tests/test_split_off_paid_portion.py`, write tests against `split_off_paid_portion` directly (not through the HTTP layer -- mirror the style of the existing tests in `backend/tests/test_installment_plan.py`, which this task's tests sit alongside conceptually though in their own file). Cover, at minimum:

  ```python
  def test_splits_a_simple_case_into_a_settled_leg_and_a_remaining_leg():
      # amount=Decimal("620.00"), amount_paid=Decimal("292.00"), date_paid=date(2026, 11, 22)
      # assert: 2 legs returned; paid leg has settled_on == date_paid, actual_amount == amount_paid,
      # amount == amount_paid, expected_date == date_paid, name == f"{orig_name} (1 of 2)";
      # remaining leg (same row as the original expense) has amount == Decimal("328.00"),
      # expected_date unchanged, name == f"{orig_name} (2 of 2)", settled_on is None;
      # both legs' installment_group_id == the original expense's own id;
      # paid_leg.amount + remaining_leg.amount == original total (Decimal equality, not float)

  def test_remaining_leg_clears_pre_existing_funding_fields():
      # original expense created with funding_account_id/funding_amount/funding_lead_days set
      # before calling split_off_paid_portion; assert all three are None/0 on the remaining leg
      # afterward, and the paid leg never had them set at all

  def test_deleting_the_paid_leg_afterward_opens_a_refund_watch():
      # call split_off_paid_portion, commit, then call cancel_installment_group on the paid leg
      # (the one with settled_on set) the same way the delete endpoint would; assert a refund-watch
      # row now exists for it and the remaining leg is untouched -- proves composition with the
      # already-shipped cascade, not new logic of this task's own
  ```

  Run: `cd backend && uv run --locked pytest tests/test_split_off_paid_portion.py -v`
  Expected: FAIL with `ImportError` or `AttributeError` (`split_off_paid_portion` doesn't exist yet).

- [ ] **Step 3: Implement `split_off_paid_portion` in `backend/services/installment_plan.py`**

  Add after `cancel_installment_group` (end of file):
  ```python
  def split_off_paid_portion(
      db: Session, user: models.User, expense: models.PlannedExpense,
      amount_paid: Decimal, date_paid: date,
  ) -> list[models.PlannedExpense]:
      """Record that part of an ordinary, ungrouped one-off has already been
      paid in real life: splits it into a new settled leg (the real amount,
      the real date) and shrinks `expense` itself down to the remaining
      balance on its existing due date. The existing row's id is always
      lower than any row created here, so it stays the group's anchor --
      unlike create_installment_group, there is no id reassignment step.
      Caller (the router) validates amount_paid < expense.amount and
      expense.installment_group_id is None before calling this, and
      commits afterward."""
      base_name = expense.name
      remaining = expense.amount - amount_paid

      paid_leg = models.PlannedExpense(
          user_id=user.id,
          name=f"{base_name} (1 of 2)",
          amount=amount_paid,
          expected_date=date_paid,
          direction=expense.direction,
          notes=expense.notes,
          category_id=expense.category_id,
          account_id=expense.account_id,
          card_id=expense.card_id,
          settled_on=date_paid,
          actual_amount=amount_paid,
      )
      db.add(paid_leg)
      db.flush()

      group_id = expense.id
      paid_leg.installment_group_id = group_id
      expense.installment_group_id = group_id
      expense.name = f"{base_name} (2 of 2)"
      expense.amount = remaining
      expense.funding_account_id = None
      expense.funding_amount = None
      expense.funding_lead_days = 0
      db.flush()

      return [paid_leg, expense]
  ```

- [ ] **Step 4: Run the Step 2 tests, verify they now pass**

  Run: `cd backend && uv run --locked pytest tests/test_split_off_paid_portion.py -v`
  Expected: PASS, all 3 tests.

- [ ] **Step 5: Add the endpoint**

  In `backend/routers/planned_expenses.py`, add `split_off_paid_portion` to the existing import from `backend.services.installment_plan` (line 6-9), then add, near the other `/{expense_id}` routes:
  ```python
  @router.post(
      "/{expense_id}/already-paid", response_model=schemas.PlannedExpenseInstallmentsOut,
  )
  def mark_expense_partially_paid(
      expense_id: int,
      body: schemas.PlannedExpensePartialPaidIn,
      db: Session = Depends(get_db),
      user: models.User = Depends(get_current_user),
  ):
      """Split an ordinary one-off into a settled already-paid leg and a
      shrunk remaining-balance leg. Not the bulk 2-6-leg split-creation
      flow -- see docs/superpowers/plans/2026-11-25-split-off-paid-portion-plan.md."""
      expense = db.query(models.PlannedExpense).filter(
          models.PlannedExpense.id == expense_id,
          models.PlannedExpense.user_id == user.id,
      ).first()
      if not expense:
          raise HTTPException(status_code=404, detail="Planned expense not found")
      if expense.installment_group_id is not None:
          raise HTTPException(status_code=422, detail="This one-off is already part of a split plan")
      if body.amount_paid >= expense.amount:
          raise HTTPException(
              status_code=422,
              detail="Amount paid must be less than the total -- use settle instead if it's fully paid",
          )
      legs = split_off_paid_portion(db, user, expense, body.amount_paid, body.date_paid)
      db.commit()
      for leg in legs:
          db.refresh(leg)
      return schemas.PlannedExpenseInstallmentsOut(legs=legs)
  ```

- [ ] **Step 6: Write a failing HTTP-level test for the two rejection cases and the happy path**

  Add to `backend/tests/test_split_off_paid_portion.py` (or a second test file if the first is already focused purely on the service function -- implementer's call, keep whichever split makes each file read cleanly):
  ```python
  def test_rejects_amount_paid_greater_than_or_equal_to_total():
      # POST .../already-paid with amount_paid == expense.amount -> 422,
      # detail mentions settle

  def test_rejects_an_expense_already_in_a_group():
      # create an installment group via the existing bulk-create flow, then
      # POST .../already-paid against one of its legs -> 422

  def test_happy_path_through_the_http_endpoint():
      # create an ordinary single expense via POST /planned-expenses, then
      # POST .../already-paid; assert 200 and the response's two legs match
      # Step 2's assertions
  ```
  Run: `cd backend && uv run --locked pytest tests/test_split_off_paid_portion.py -v`
  Expected: the two rejection tests pass immediately (routing + validation already written in Step 5); the happy-path HTTP test passes too. If anything fails here, it indicates a Step 5 wiring mistake, not a missing feature -- fix Step 5, not the test.

- [ ] **Step 7: Full backend suite + coverage floor**

  Run: `cd backend && uv run --locked pytest`
  Expected: all tests pass (no regressions), coverage stays at or above the floor in `backend/.coveragerc`.

- [ ] **Step 8: Commit**

  ```bash
  git add backend/schemas.py backend/services/installment_plan.py backend/routers/planned_expenses.py backend/tests/test_split_off_paid_portion.py
  git commit -m "Add endpoint to split an already-paid portion off an existing one-off"
  ```

---

### Task 2: Frontend -- "Already paid part of this?" action on the edit form

**Files:**
- Modify: `frontend/src/api/index.ts` (new client function)
- Modify: `frontend/src/pages/Forecast.tsx` (new UI inside the existing per-row edit block)

**Interfaces:**
- Consumes: Task 1's `POST /planned-expenses/{expense_id}/already-paid`, request body `{amount_paid: number, date_paid: string}`, response `{legs: PlannedExpenseOut[]}`. `today()` from `../lib/utils` (already imported in `Forecast.tsx`).
- Produces: nothing consumed elsewhere -- purely local UI state and a mutation, same shape as this file's existing `settleMut`/`createExpenseMut` pattern.

- [ ] **Step 1: Add the API client function**

  In `frontend/src/api/index.ts`, alongside the other `plannedExpensesApi` entries (near `previewInstallments`/`createInstallments`, `frontend/src/api/index.ts:328-330`), add:
  ```ts
  alreadyPaid: (id: number, data: object) =>
    api.post(`/planned-expenses/${id}/already-paid`, data).then((r) => r.data),
  ```

- [ ] **Step 2: Add component state and the mutation**

  In `frontend/src/pages/Forecast.tsx`, alongside the existing `settleId`/`settleAmount` state (near line 341), add:
  ```ts
  const [partialPayId, setPartialPayId] = useState<number | null>(null);
  const [partialPayAmount, setPartialPayAmount] = useState("");
  const [partialPayDate, setPartialPayDate] = useState(today());
  ```
  Alongside `updateExpenseMut` (after it), add:
  ```ts
  const partialPayMut = useMutation({
    mutationFn: ({ id, data }: { id: number; data: object }) => plannedExpensesApi.alreadyPaid(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["planned-expenses"] });
      qc.invalidateQueries({ queryKey: ["forecast-quarters"] });
      qc.invalidateQueries({ queryKey: ["forecast-multi-year"] });
      setPartialPayId(null);
      setPartialPayAmount("");
      setPartialPayDate(today());
      setEditExpenseId(null);
    },
  });
  ```

- [ ] **Step 3: Add the UI inside the edit branch**

  In the `editExpenseId === pe.id` block, immediately after the existing Save/Cancel button row (after the closing `</div>` that follows the Cancel button, i.e. right before that branch's own closing `</div>`), add a reveal mirroring the existing "Reconcile this" / settle-inline-form pattern used later in this same file for stylistic consistency (`bg-amber-50 dark:bg-amber-900/15` panel, `btn-primary`/`btn-secondary text-xs` buttons):
  ```tsx
  {partialPayId === pe.id ? (
    <div className="mt-2 flex flex-wrap items-center gap-2 bg-amber-50 dark:bg-amber-900/15 rounded-md px-3 py-2">
      <span className="text-xs text-gray-600 dark:text-gray-300">Amount paid</span>
      <input
        type="number" step="0.01" autoFocus
        className="input py-1 text-sm w-28"
        value={partialPayAmount}
        onChange={e => setPartialPayAmount(e.target.value)}
      />
      <span className="text-xs text-gray-600 dark:text-gray-300">on</span>
      <input
        type="date"
        className="input py-1 text-sm"
        value={partialPayDate}
        onChange={e => setPartialPayDate(e.target.value)}
      />
      <button
        className="btn-primary text-xs px-2 py-1"
        disabled={
          !(parseFloat(partialPayAmount) > 0 && parseFloat(partialPayAmount) < parseFloat(editExpenseForm.amount))
          || !partialPayDate || partialPayMut.isPending
        }
        onClick={() => partialPayMut.mutate({ id: pe.id, data: { amount_paid: parseFloat(partialPayAmount), date_paid: partialPayDate } })}>
        {partialPayMut.isPending ? "Saving…" : "Confirm"}
      </button>
      <button
        className="text-xs text-gray-400 hover:text-gray-600"
        onClick={() => { setPartialPayId(null); setPartialPayAmount(""); }}>
        Cancel
      </button>
      {partialPayMut.isError && <p className="w-full text-xs text-red-600 dark:text-red-400">Couldn't save that. Try again.</p>}
    </div>
  ) : (
    <button
      className="mt-2 text-xs text-amber-700 dark:text-amber-400 hover:underline"
      onClick={() => { setPartialPayId(pe.id); setPartialPayAmount(""); setPartialPayDate(today()); }}>
      Already paid part of this?
    </button>
  )}
  ```
  The `disabled` check's upper bound (`< parseFloat(editExpenseForm.amount)`) uses the live edit form's amount field, not `pe.amount`, so it stays correct if the user also changed the amount in the same edit session before clicking this.

- [ ] **Step 4: Type-check and build**

  Run: `cd frontend && bunx vite build`
  Expected: builds clean, no new TypeScript errors beyond the existing tracked baseline (confirm the count hasn't grown, same check as the previous task today).

- [ ] **Step 5: Run the existing frontend test suite**

  Run: `cd frontend && bun test`
  Expected: all existing tests still pass -- no new test file, per the Global Constraints note on this repo's frontend test conventions.

- [ ] **Step 6: Commit**

  ```bash
  git add frontend/src/api/index.ts frontend/src/pages/Forecast.tsx
  git commit -m "Add \"already paid part of this\" action to the one-off edit form"
  ```
