import { describe, expect, test } from "bun:test";
import { axisTicks, monthTicks, resolveRange, sampleLows, tickLabel, yearStarts } from "../src/lib/forecastRange";

const quarters = (years: number[]) => years.flatMap((year) => [1, 2, 3, 4].map((quarter) => ({ year, quarter })));

describe("resolveRange", () => {
  test("next 4 quarters in Q4 reaches into next year's Q1-Q3", () => {
    const r = resolveRange("next4", new Date(2026, 9, 16));
    expect(r.startYear).toBe(2026);
    expect(r.years).toBe(2);
    expect(quarters([2026, 2027]).filter(r.keep)).toEqual([
      { year: 2026, quarter: 4 }, { year: 2027, quarter: 1 }, { year: 2027, quarter: 2 }, { year: 2027, quarter: 3 },
    ]);
    expect(r.label).toBe("Q4 2026 – Q3 2027");
  });

  test("next 4 quarters in Q1 stays inside one year", () => {
    const r = resolveRange("next4", new Date(2026, 1, 10));
    expect(r.years).toBe(1);
    expect(quarters([2026]).filter(r.keep).length).toBe(4);
  });

  test("a calendar year and a multi-year span", () => {
    expect(resolveRange("year:2027", new Date(2026, 9, 16))).toMatchObject({ startYear: 2027, years: 1 });
    expect(resolveRange("span:3", new Date(2026, 9, 16))).toMatchObject({ startYear: 2026, years: 3, label: "2026–2028" });
  });
});

describe("sampleLows", () => {
  const days = Array.from({ length: 730 }, (_, i) => {
    const d = new Date(2026, 0, 1 + i);
    return { date: d.toISOString().slice(0, 10), balance: 1000 };
  });

  test("keeps the trough and today, and thins a long span", () => {
    days[400] = { ...days[400], balance: -50 };
    const today = days[300].date;
    const out = sampleLows(days, today);
    expect(out.length).toBeLessThanOrEqual(190);
    expect(out.some((d) => d.balance === -50)).toBe(true);
    expect(out.some((d) => d.date === today)).toBe(true);
    expect(out.map((d) => d.date)).toEqual([...out.map((d) => d.date)].sort());
  });

  test("a short (zoomed) span keeps every day", () => {
    const short = days.slice(0, 60);
    expect(sampleLows(short, "2099-01-01").length).toBe(60);
  });
});

test("axis helpers", () => {
  expect(tickLabel("2027-01-04", true)).toBe("Jan '27");
  expect(tickLabel("2027-01-04", false)).toBe("Jan 4");
  expect(yearStarts(["2026-12-30", "2027-01-02", "2027-06-01", "2028-01-01"])).toEqual(["2027-01-02", "2028-01-01"]);
  const twoYears = Array.from({ length: 24 }, (_, i) => `${2026 + Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, "0")}-01`);
  expect(monthTicks(twoYears).length).toBe(12);
});

test("a zoomed window gets about a dozen day ticks", () => {
  const dates = Array.from({ length: 90 }, (_, i) => new Date(2026, 10, 1 + i).toISOString().slice(0, 10));
  const { ticks, format } = axisTicks(dates);
  expect(ticks.length).toBeLessThanOrEqual(12);
  expect(format("2026-11-12")).toBe("Nov 12");
});
