import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { UpcomingBillsCard } from "./UpcomingBillsCard";
import { BALANCE_MASK } from "../../store/balanceVisibility";
import { fmt } from "../../lib/utils";

// Made-up fixture amounts only (public repo).
const future = (days: number) => {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
const bills = () => [
  { recurring_item_id: 1, name: "Fake Power Co", due_date: future(5), amount: "187.43", is_actual: false },
  { recurring_item_id: 2, name: "Fake Water Co", due_date: future(9), amount: "64.91", is_actual: true },
];

const g = globalThis as unknown as { localStorage?: Storage };
const original = g.localStorage;
beforeEach(() => {
  g.localStorage = { getItem: () => "1", setItem: () => {} } as unknown as Storage;
});
afterEach(() => {
  if (original === undefined) delete g.localStorage;
  else g.localStorage = original;
});

const render = (b: any[], hasRecurring: boolean, hidden: boolean) =>
  renderToStaticMarkup(
    <MemoryRouter>
      <UpcomingBillsCard bills={b} hasRecurring={hasRecurring} hidden={hidden} />
    </MemoryRouter>,
  );

describe("UpcomingBillsCard", () => {
  test("shown mode lists names and amounts", () => {
    const html = render(bills(), true, false);
    expect(html).toContain("Fake Power Co");
    expect(html).toContain("Fake Water Co");
    expect(html).toContain(fmt("187.43"));
    expect(html).toContain(fmt("64.91"));
  });

  test("hidden mode masks amounts and leaks no digits", () => {
    const html = render(bills(), true, true);
    const content = html.replace(/ class="[^"]*"/g, "").replace(/<svg[\s\S]*?<\/svg>/g, "");
    expect(html).toContain(BALANCE_MASK);
    for (const leak of ["187", "64.91", "$"]) expect(content).not.toContain(leak);
  });

  test("empty with recurring items says no bills due", () => {
    expect(render([], true, false)).toContain("No bills due in the next 30 days");
  });
});
