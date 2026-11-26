import { describe, expect, test } from "bun:test";
import { barHeightPx, barLabel, barTone, cushionOffsetPx, lowestIndex, monthTicks, safetyMarginTone, scaleMaxFor, spendableTone, type WeeklyLow } from "./weeklyLows";

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
    expect(safetyMarginTone(0)).toBe("good");
    expect(safetyMarginTone(-0.01)).toBe("danger");
    expect(safetyMarginTone(5)).toBe("good");
  });
});

describe("spendableTone", () => {
  test("boundaries", () => {
    expect(spendableTone(0)).toBe("good");
    expect(spendableTone(-0.01)).toBe("caution");
    expect(spendableTone(5)).toBe("good");
  });
});

describe("chart geometry", () => {
  test("scaleMaxFor takes the larger of the top low and the cushion", () => {
    expect(scaleMaxFor([low({ amount: "2500.00" }), low({ amount: "800.00" }), low({ amount: null })], 1000)).toBe(2500);
    expect(scaleMaxFor([low({ amount: "300.00" })], 1000)).toBe(1000);
  });
  test("scaleMaxFor never returns 0", () => {
    expect(scaleMaxFor([], 0)).toBe(1);
    expect(scaleMaxFor([low({ amount: null })], 0)).toBe(1);
    expect(scaleMaxFor([low({ amount: "-50.00" })], 0)).toBe(1);
  });
  test("barHeightPx", () => {
    expect(barHeightPx("2500.00", 2500)).toBe(64);
    expect(barHeightPx("800.00", 2500)).toBe(20);
    expect(barHeightPx("-50.00", 2500)).toBe(4);
    expect(barHeightPx("10.00", 2500)).toBe(4);
    expect(barHeightPx(null, 2500)).toBe(0);
  });
  test("cushionOffsetPx", () => {
    expect(cushionOffsetPx(1000, 2500)).toBe(26);
    expect(cushionOffsetPx(0, 2500)).toBe(0);
    expect(cushionOffsetPx(-5, 2500)).toBe(0);
  });
  test("a non-finite cushion is treated as 0", () => {
    expect(scaleMaxFor([low({ amount: "800.00" })], NaN)).toBe(800);
    expect(cushionOffsetPx(NaN, 2500)).toBe(0);
  });
});
