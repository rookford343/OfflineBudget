import { describe, expect, test } from "bun:test";
import type { HistoryCause } from "../src/api";
import { dayLabel, displayHeadline, itemMoney, mathFigures, periodLine, sameFigure, signedMoney } from "../src/lib/historyMoney";

describe("history money display", () => {
  test("hidden mode masks item and signed amounts", () => {
    expect(itemMoney(true, "250.00")).not.toMatch(/\d/);
    expect(signedMoney(true, "-400.00", true)).not.toMatch(/\d/);
  });
  test("visible mode shows them", () => {
    expect(itemMoney(false, "1234.50")).toBe("$1,234.50");
    expect(signedMoney(false, "-400.00", true)).toBe("−$400.00");
    expect(signedMoney(false, "12.50", true)).toBe("+$12.50");
  });
  test("an inherited item has no amount to show", () => {
    expect(itemMoney(false, null)).toBe("");
  });
  test("sameFigure compares displayed figures, not decimal scale", () => {
    expect(sameFigure("-30.00", "-30")).toBe(true);
    expect(sameFigure("30.00", "-30.00")).toBe(false);
  });
});

describe("statement wording", () => {
  test("periodLine words a fall and a rise", () => {
    expect(periodLine(false, "-906.00", "2000.00", "Nov 7")).toBe("down $906.00 since Nov 7, from $2,000.00");
    expect(periodLine(false, "50.00", "100.00", "Nov 7")).toBe("up $50.00 since Nov 7, from $100.00");
  });
  test("periodLine says no net change", () => {
    expect(periodLine(false, "0.00", "100.00", "Nov 7")).toBe("no net change since Nov 7");
  });
  test("dayLabel names today and reads the date as local", () => {
    const today = new Date(2026, 10, 10);
    expect(dayLabel("2026-11-10", today)).toBe("Today, Nov 10");
    expect(dayLabel("2026-11-09", today)).toBe("Mon, Nov 9");
  });
  test("mathFigures shows before and after, or says no change", () => {
    expect(mathFigures(false, "2032.00", "1894.00")).toBe("$2,032.00 → $1,894.00");
    expect(mathFigures(false, "-800.00", "-800.00")).toBe("−$800.00, no change");
  });
  test("mathFigures words a one-sided line", () => {
    expect(mathFigures(false, null, "25.00")).toBe("added, $25.00");
    expect(mathFigures(false, "25.00", null)).toBe("removed, was $25.00");
  });
  test("hidden mode masks statement figures", () => {
    expect(periodLine(true, "-906.00", "2000.00", "")).not.toMatch(/\d/);
    expect(mathFigures(true, "2032.00", "1894.00")).not.toMatch(/\d/);
  });
});

describe("displayHeadline", () => {
  const cause = (items: { name: string; amount: string | null }[]): HistoryCause => (
    { text: "", amount: null, head: "", items }
  );

  test("one event, one item appends the item's name", () => {
    const events = [cause([{ name: "Example Coffee Co", amount: "-4.50" }])];
    expect(displayHeadline("Pending charges changed", events)).toBe("Pending charges changed: Example Coffee Co");
  });
  test("one event, two items leaves the headline unchanged", () => {
    const events = [cause([{ name: "Example Coffee Co", amount: "-4.50" }, { name: "Example Grocer", amount: "-32.10" }])];
    expect(displayHeadline("Pending charges changed", events)).toBe("Pending charges changed");
  });
  test("two events leaves the headline unchanged", () => {
    const events = [cause([{ name: "Example Coffee Co", amount: "-4.50" }]), cause([{ name: "Example Grocer", amount: "-32.10" }])];
    expect(displayHeadline("Pending charges changed", events)).toBe("Pending charges changed");
  });
  test("zero events leaves the headline unchanged", () => {
    expect(displayHeadline("Balance updated", [])).toBe("Balance updated");
  });
});
