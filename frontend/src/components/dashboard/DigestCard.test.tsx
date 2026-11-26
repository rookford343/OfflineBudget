import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { DigestCard } from "./DigestCard";
import { BALANCE_MASK } from "../../store/balanceVisibility";

// Made-up fixture amounts only (public repo).
const digest = (): any => ({
  total_spent: "812.47",
  categories: [
    { category_id: 1, category_name: "Groceries", total: "431.29" },
    { category_id: 2, category_name: "Fuel", total: "93.18" },
  ],
  top_merchants: [
    { name: "Corner Market", total: "275.63" },
    { name: "Gas Stop", total: "93.18" },
  ],
});

const g = globalThis as unknown as { localStorage?: Storage };
const original = g.localStorage;
beforeEach(() => {
  g.localStorage = { getItem: () => "1", setItem: () => {} } as unknown as Storage;
});
afterEach(() => {
  if (original === undefined) delete g.localStorage;
  else g.localStorage = original;
});

const render = (d: any, hidden: boolean, budget = new Map<number, any>()) =>
  renderToStaticMarkup(
    <DigestCard title="Monthly Digest — Nov 1 – Nov 26" digest={d} budgetByCategory={budget} hidden={hidden} emptyText="No spending yet this month." />,
  );

describe("DigestCard", () => {
  test("shown: title, total, categories, merchants; merchants after categories", () => {
    const html = render(digest(), false);
    for (const s of ["Monthly Digest — Nov 1 – Nov 26", "$812.47", "Groceries", "Fuel", "Corner Market", "Gas Stop"]) {
      expect(html).toContain(s);
    }
    expect(html.indexOf("Top Merchants")).toBeGreaterThan(html.indexOf("By Category"));
  });

  test("empty categories show emptyText and no merchants section", () => {
    const html = render({ total_spent: "0", categories: [], top_merchants: [] }, false);
    expect(html).toContain("No spending yet this month.");
    expect(html).not.toContain("Top Merchants");
    expect(html).not.toContain("By Category");
  });

  test("hidden: mask only, no $ or amount digits", () => {
    const html = render(digest(), true);
    const content = html.replace(/ class="[^"]*"/g, "").replace(/ style="[^"]*"/g, "").replace(/<svg[\s\S]*?<\/svg>/g, "");
    expect(html).toContain(BALANCE_MASK);
    expect(content).not.toContain("$");
    for (const leak of ["812", "431", "93.18", "275", "47", "29"]) expect(content).not.toContain(leak);
  });

  test("over-budget category gets the over-budget marker", () => {
    const over = render(digest(), false, new Map([[1, { budgeted: "100.00", actual_total: "150.00" }]]));
    expect(over).toContain("border-red-500");
    const under = render(digest(), false, new Map([[1, { budgeted: "500.00", actual_total: "150.00" }]]));
    expect(under).not.toContain("border-red-500");
  });
});
