import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { BalanceFlowCard } from "./BalanceFlowCard";

// Made-up fixture amounts only (public repo).
const g = globalThis as unknown as { localStorage?: Storage };
const original = g.localStorage;
beforeEach(() => {
  g.localStorage = { getItem: () => null, setItem: () => {} } as unknown as Storage;
});
afterEach(() => {
  if (original === undefined) delete g.localStorage;
  else g.localStorage = original;
});

const base = {
  balanceFlow: [
    { date: "2026-11-01", projected_balance: "4321.09" },
    { date: "2026-11-02", projected_balance: "4287.65" },
  ],
  lastMonthFlow: [{ date: "2026-10-01", projected_balance: "4111.22" }],
  baseline: null,
  flowFigures: { month_to_date_change: "-33.44", drift_from_forecast: null },
  lastMonthRange: { start: "2026-10-01", end: "2026-10-31" },
  monthStart: "2026-11-01",
  todayStr: "2026-11-02",
  isDark: false,
};

const strip = (html: string) => html.replace(/<[^>]*>/g, " ");

describe("BalanceFlowCard", () => {
  test("renders the card header", () => {
    const html = renderToStaticMarkup(<BalanceFlowCard {...base} balancesHidden={false} />);
    expect(html).toContain("Balance Flow");
  });

  test("fill classes appear only when fill is true", () => {
    const off = renderToStaticMarkup(<BalanceFlowCard {...base} balancesHidden={false} />);
    const on = renderToStaticMarkup(<BalanceFlowCard {...base} balancesHidden={false} fill />);
    for (const c of ["h-full flex flex-col", "flex-1 min-h-[220px]"]) {
      expect(off).not.toContain(c);
      expect(on).toContain(c);
    }
  });

  test("renders nothing without data", () => {
    const html = renderToStaticMarkup(
      <BalanceFlowCard {...base} balanceFlow={[]} lastMonthFlow={[]} balancesHidden={false} />,
    );
    expect(html).toBe("");
  });

  test("hidden balances leak no amount digits or $", () => {
    const html = renderToStaticMarkup(<BalanceFlowCard {...base} balancesHidden={true} />);
    expect(html).toContain("Balance Flow");
    const text = strip(html);
    expect(text).not.toContain("$");
    for (const d of ["4321", "4287", "4111", "33.44", "33"]) expect(text).not.toContain(d);
  });
});
