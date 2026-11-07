/** Pure helpers for the Budget page. The backend's GET /budget/plan does the
 * money math (Committed + Flexible = Budget, Left to assign, Track Budgets
 * totals and each line's available/left); these only decide how to show it
 * and which month a Flexible save writes to. Amounts arrive as decimal
 * strings. */

const cents = (v: string | number | null | undefined): number =>
  Math.round(parseFloat(String(v ?? "0")) * 100) || 0;

export type PlanTrackLine = {
  category_id: number;
  category_name: string;
  is_group: boolean;
  budget: string;
  actual_total: string;
  rollover_enabled?: boolean;
  rollover_balance?: string;
  available: string;
  left: string;
};

/** The plan's Track Budgets headline, as the backend sends it. */
export type TrackTotals = {
  budgeted: string; available: string; spent: string; left: string; pct: string; over_count: number;
};

export type OverviewRow = {
  category_id: number;
  category_name: string;
  parent_id?: number | null;
  category_type?: string;
  budgeted: string;
  actual_total: string;
  is_assignable?: boolean;
};

/** Green with "left to assign" at or above zero, red "over-assigned" below. */
export function leftToAssignStatus(value: string | number): { over: boolean; amount: number; label: string } {
  const c = cents(value);
  return c < 0
    ? { over: true, amount: Math.abs(c) / 100, label: "over-assigned" }
    : { over: false, amount: c / 100, label: "left to assign" };
}

/** Which month a Flexible save writes. Every-month (0) by default so a new
 * month never starts unbudgeted -- except an assignable bucket while
 * carry-forward is off, whose every-month row the backend ignores by design. */
export function flexibleSaveMonth(month: number, isAssignable: boolean, carryForward: boolean): number {
  return isAssignable && !carryForward ? month : 0;
}

/** Expense categories with spend this month and no Budget behind them.
 * A category is covered if it has a Track line, if its parent has a group
 * line (the group covers its children), or if it is the parent of a covered
 * category (its spend is their rolled-up spend, so offering it would
 * double-count). Highest spend first. */
export function unbudgetedSpend(overview: OverviewRow[], lines: PlanTrackLine[]): OverviewRow[] {
  const lineIds = new Set(lines.map(l => l.category_id));
  const groupIds = new Set(lines.filter(l => l.is_group).map(l => l.category_id));
  const parentOf = new Map(overview.map(r => [r.category_id, r.parent_id ?? null]));
  const parentsOfCovered = new Set(
    [...lineIds].map(id => parentOf.get(id)).filter((p): p is number => p != null),
  );
  return overview
    .filter(r => (r.category_type ?? "expense") === "expense")
    .filter(r => cents(r.actual_total) > 0)
    .filter(r => !lineIds.has(r.category_id))
    .filter(r => !(r.parent_id != null && groupIds.has(r.parent_id)))
    .filter(r => !parentsOfCovered.has(r.category_id))
    .sort((a, b) => cents(b.actual_total) - cents(a.actual_total));
}
