import { describe, expect, test } from "bun:test";
import { describeSplit, splitBonus, type AllocationStep } from "../src/lib/bonusSplit";

const fixed = (account_id: number, value: string, round_to: string | null = null): AllocationStep =>
  ({ account_id, kind: "fixed", value, round_to });
const percent = (account_id: number, value: string, round_to: string | null = null): AllocationStep =>
  ({ account_id, kind: "percent", value, round_to });
const rest = (account_id: number, round_to: string | null = null): AllocationStep =>
  ({ account_id, kind: "rest", value: null, round_to });

describe("splitBonus", () => {
  test("the help-text example: fixed then rest, rounded down", () => {
    // $25,000 to Money Market, the rest to Savings rounded down to $1,000.
    const steps = [fixed(1, "25000"), rest(2, "1000")];
    const legs = splitBonus(48656, steps, null, null);
    expect(legs).toEqual([
      { account_id: 1, amount: 25000 },
      { account_id: 2, amount: 23000 },
    ]);
    const moved = legs.reduce((sum, l) => sum + l.amount, 0);
    expect(48656 - moved).toBeCloseTo(656, 5); // left in checking
  });

  test("shortfall: bonus can't cover the fixed steps, all of it goes to the shortfall account rounded down", () => {
    const steps = [fixed(1, "25000")];
    const legs = splitBonus(20500, steps, 3, "1000");
    expect(legs).toEqual([{ account_id: 3, amount: 20000 }]);
  });

  test("no shortfall account configured: the fixed step just clamps to what's there", () => {
    const steps = [fixed(1, "25000")];
    const legs = splitBonus(20500, steps, null, null);
    expect(legs).toEqual([{ account_id: 1, amount: 20500 }]);
  });

  test("percent then rest: percent is of the total, rest takes what's left", () => {
    // 50% of a 10,050 bonus, rounded down to $100, then the rest (no rounding).
    const steps = [percent(1, "50", "100"), rest(2)];
    const legs = splitBonus(10050, steps, null, null);
    expect(legs).toEqual([
      { account_id: 1, amount: 5000 },
      { account_id: 2, amount: 5050 },
    ]);
  });

  test("never moves more than the total, even when percent steps overlap past 100%", () => {
    const steps = [percent(1, "60"), percent(2, "60")];
    const legs = splitBonus(1000, steps, null, null);
    const moved = legs.reduce((sum, l) => sum + l.amount, 0);
    expect(moved).toBeLessThanOrEqual(1000);
    expect(legs).toEqual([
      { account_id: 1, amount: 600 },
      { account_id: 2, amount: 400 }, // clamped: 60% of 1000 would be 600, only 400 remains
    ]);
  });

  test("a zero amount step is skipped entirely", () => {
    const steps = [fixed(1, "25000"), percent(2, "0"), rest(3)];
    const legs = splitBonus(30000, steps, null, null);
    expect(legs).toEqual([
      { account_id: 1, amount: 25000 },
      { account_id: 3, amount: 5000 },
    ]);
  });
});

describe("describeSplit", () => {
  const names: Record<number, string> = { 1: "Money Market", 2: "Savings" };
  const nameOf = (id: number) => names[id] ?? "that account";
  const fmt = (n: number) => `$${n.toFixed(2)}`;

  test("renders the full sentence with a remainder left in checking", () => {
    const legs = splitBonus(48656, [fixed(1, "25000"), rest(2, "1000")], null, null);
    expect(describeSplit(48656, legs, nameOf, fmt)).toBe(
      "$25000.00 to Money Market, $23000.00 to Savings, $656.00 stays in checking.",
    );
  });

  test("no remainder: nothing extra stays in checking", () => {
    const legs = splitBonus(45000, [fixed(1, "25000"), rest(2)], null, null);
    expect(describeSplit(45000, legs, nameOf, fmt)).toBe(
      "$25000.00 to Money Market, $20000.00 to Savings.",
    );
  });

  test("no steps configured at all: everything stays in checking", () => {
    expect(describeSplit(1000, [], nameOf, fmt)).toBe("$1000.00 stays in checking.");
  });
});
