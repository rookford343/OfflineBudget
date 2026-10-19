import { describe, expect, test } from "bun:test";
import {
  availableOf, flexibleSaveMonth, leftToAssignStatus, trackTotals, unbudgetedSpend,
  type OverviewRow, type PlanTrackLine,
} from "../src/lib/budgetPlan";

const line = (category_id: number, budget: string, actual_total: string, extra: Partial<PlanTrackLine> = {}): PlanTrackLine =>
  ({ category_id, category_name: `C${category_id}`, is_group: false, budget, actual_total, ...extra });
const ov = (category_id: number, actual_total: string, parent_id: number | null = null, category_type = "expense"): OverviewRow =>
  ({ category_id, category_name: `C${category_id}`, parent_id, category_type, budgeted: "0", actual_total });

describe("leftToAssignStatus", () => {
  test("zero and above is left to assign", () => {
    expect(leftToAssignStatus("100.00")).toEqual({ over: false, amount: 100, label: "left to assign" });
    expect(leftToAssignStatus("0.00").over).toBe(false);
  });
  test("below zero is over-assigned, shown as a positive amount", () => {
    expect(leftToAssignStatus("-250.00")).toEqual({ over: true, amount: 250, label: "over-assigned" });
  });
});

describe("flexibleSaveMonth", () => {
  test("every month by default", () => {
    expect(flexibleSaveMonth(10, false, false)).toBe(0);
    expect(flexibleSaveMonth(10, true, true)).toBe(0);
  });
  test("an assignable bucket with carry-forward off saves for the viewed month only", () => {
    expect(flexibleSaveMonth(10, true, false)).toBe(10);
  });
});

describe("trackTotals", () => {
  test("budgeted is the plain sum of line budgets", () => {
    const t = trackTotals([line(1, "3000.00", "2050.00"), line(2, "500.00", "600.00"), line(3, "140.10", "0")]);
    expect(t.budgeted).toBe(3640.1);
    expect(t.spent).toBe(2650);
    expect(t.left).toBe(990.1);
    expect(t.overCount).toBe(1);
  });
  test("rollover only counts when enabled", () => {
    expect(availableOf(line(1, "100.00", "0", { rollover_enabled: true, rollover_balance: "50.00" }))).toBe(150);
    expect(availableOf(line(1, "100.00", "0", { rollover_enabled: false, rollover_balance: "50.00" }))).toBe(100);
  });
  test("no lines means nothing over and no division by zero", () => {
    expect(trackTotals([])).toMatchObject({ available: 0, pct: 0, overCount: 0 });
  });
});

describe("unbudgetedSpend", () => {
  // 1 Necessities (group line) > 2 Mortgage, 3 Groceries; 4 Wants > 5 Shopping (line), 6 Dining;
  // 7 Charity (no line); 8 Salary (income).
  const overview = [
    ov(1, "2050.00"), ov(2, "2000.00", 1), ov(3, "50.00", 1),
    ov(4, "80.00"), ov(5, "30.00", 4), ov(6, "50.00", 4),
    ov(7, "200.00"), ov(8, "10.00", null, "income"),
  ];
  const lines = [line(1, "3000.00", "2050.00", { is_group: true }), line(5, "500.00", "30.00")];

  test("offers only uncovered expense categories, highest spend first", () => {
    expect(unbudgetedSpend(overview, lines).map(r => r.category_id)).toEqual([7, 6]);
  });
});
