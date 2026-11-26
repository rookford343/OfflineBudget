import { describe, expect, test } from "bun:test";
import { barLabel, barTone, lowestIndex, monthTicks, safetyMarginTone, type WeeklyLow } from "./weeklyLows";

// Made-up amounts only (public repo).
const low = (over: Partial<WeeklyLow> = {}): WeeklyLow => ({
  start: "2026-12-01",
  end: "2026-12-07",
  amount: "1050.00",
  date: "2026-12-03",
  status: "ok",
  ...over,
});

describe("lowestIndex", () => {
  test("earliest wins on a tie", () => {
    expect(lowestIndex([low({ amount: "900.00" }), low({ amount: "800.00" }), low({ amount: "800.00" })])).toBe(1);
  });
  test("skips null amounts", () => {
    expect(lowestIndex([low({ amount: null }), low({ amount: "500.00" })])).toBe(1);
  });
  test("all-null gives null", () => {
    expect(lowestIndex([low({ amount: null }), low({ amount: null })])).toBeNull();
    expect(lowestIndex([])).toBeNull();
  });
});

describe("barTone", () => {
  test("lowest warning stays warning", () => expect(barTone(low({ status: "warning" }), true)).toBe("warning"));
  test("lowest ok is accent", () => expect(barTone(low(), true)).toBe("accent"));
  test("non-lowest ok is bar", () => expect(barTone(low(), false)).toBe("bar"));
  test("null amount is a gap even when lowest", () =>
    expect(barTone(low({ amount: null, date: null }), true)).toBe("gap"));
  test("danger beats everything", () => expect(barTone(low({ status: "danger" }), true)).toBe("danger"));
});

describe("barLabel", () => {
  test("shown", () => expect(barLabel(low(), false)).toBe("Week of Dec 1: low $1,050.00 on Dec 3"));
  test("hidden masks the amount and keeps dates", () => {
    const s = barLabel(low(), true);
    expect(s).toContain("••••••");
    expect(s).not.toContain("$");
    expect(s).not.toContain("1,050");
    expect(s).not.toContain("1050");
    expect(s).toBe("Week of Dec 1: low •••••• on Dec 3");
  });
  test("gap", () => expect(barLabel(low({ amount: null, date: null }), true)).toBe("Week of Dec 1: no forecast low"));
});

describe("monthTicks", () => {
  test("three months of weekly buckets", () => {
    const lows: WeeklyLow[] = [];
    const d = new Date("2026-12-01T12:00:00");
    for (let i = 0; i < 13; i++) {
      const s = new Date(d.getTime() + i * 7 * 86400000).toISOString().slice(0, 10);
      lows.push(low({ start: s }));
    }
    const ticks = monthTicks(lows);
    expect(ticks.length).toBeGreaterThanOrEqual(3);
    expect(ticks.length).toBeLessThanOrEqual(4);
    expect(ticks[0]).toEqual({ index: 0, label: "Dec" });
  });
});

describe("safetyMarginTone", () => {
  test("boundaries", () => {
    expect(safetyMarginTone(0)).toBe("ink");
    expect(safetyMarginTone(-0.01)).toBe("danger");
    expect(safetyMarginTone(5)).toBe("ink");
  });
});
