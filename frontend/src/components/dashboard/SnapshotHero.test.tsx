import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SnapshotHero } from "./SnapshotHero";
import { BALANCE_MASK } from "../../store/balanceVisibility";

// Made-up fixture amounts only (public repo).
const baseSnapshot = (): any => ({
  left_to_spend: "412.34",
  left_to_spend_weekly: "98.76",
  spendable_today: "-14.21",
  on_pace: false,
  safety_margin: "1987.65",
  safety_margin_weekly: "-250.55",
  safety_margin_today: "-35.77",
  savings_pull_needed: "250.55",
  safety_cushion: "777.00",
  lookahead_minimum: "-250.55",
  lookahead_minimum_date: "2026-12-14",
  lookahead_status: "danger",
  next_month_minimum: "-250.55",
  next_month_minimum_date: "2026-12-14",
  next_month_label: "Dec",
  move_to_checking_needed: "333.21",
  weekly_lows: [
    { start: "2026-12-01", end: "2026-12-07", amount: "1050.00", date: "2026-12-03", status: "ok" },
    { start: "2026-12-08", end: "2026-12-14", amount: "-250.55", date: "2026-12-14", status: "danger" },
    { start: "2026-12-15", end: "2026-12-21", amount: null, date: null, status: "ok" },
    { start: "2026-12-22", end: "2026-12-28", amount: "640.10", date: "2026-12-24", status: "warning" },
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

function render(snapshot: any, hidden: boolean) {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <SnapshotHero snapshot={snapshot} primaryCheckingId={1} hidden={hidden} isWide />
    </QueryClientProvider>,
  );
}

describe("SnapshotHero", () => {
  test("hidden mode leaks no amount, including title and aria-label", () => {
    const html = render(baseSnapshot(), true);
    // Classes (bg-red-500) and inline SVG icon paths carry digits; "below $0" is a static string.
    const content = html.replace(/ class="[^"]*"/g, "").replace(/below \$0/g, "").replace(/ style="[^"]*"/g, "").replace(/<svg[\s\S]*?<\/svg>/g, "");
    expect(html).toContain(BALANCE_MASK);
    expect(content).not.toContain("$");
    for (const leak of ["412", "98.76", "14.21", "1987", "1,987", "250", "35.77", "777", "333", "1050", "1,050", "640"]) {
      expect(content).not.toContain(leak);
    }
    expect(content).toContain('aria-label="Week of Dec 1: low •••••• on Dec 3"');
    expect(content).toContain("Week of Dec 15: no forecast low");
  });

  test("positive Safety Margin is not amber", () => {
    const s = baseSnapshot();
    s.safety_margin_weekly = "250.00";
    s.savings_pull_needed = "0";
    const html = render(s, false);
    const fig = html.match(/<p data-testid="sm-figure"[^>]*>/)![0];
    expect(fig).not.toContain("amber");
    expect(fig).not.toContain("warn");
    expect(fig).not.toContain("red");
    expect(fig).toContain("text-ink");
  });

  test("negative Safety Margin is red", () => {
    const html = render(baseSnapshot(), false);
    expect(html.match(/<p data-testid="sm-figure"[^>]*>/)![0]).toContain("text-red-600");
  });

  test("no weekly_lows still renders without a chart", () => {
    const s = baseSnapshot();
    delete s.weekly_lows;
    const html = render(s, false);
    expect(html).toContain("Household Snapshot");
    expect(html).not.toContain("Checking low point each week");
  });
});
