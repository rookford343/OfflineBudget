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

  test("positive Safety Margin is green, never amber or red", () => {
    for (const v of ["250.00", "0.00"]) {
      const s = baseSnapshot();
      s.safety_margin_weekly = v;
      s.savings_pull_needed = "0";
      const fig = render(s, false).match(/<p data-testid="sm-figure"[^>]*>/)![0];
      expect(fig).toContain("text-emerald-600");
      expect(fig).not.toContain("amber");
      expect(fig).not.toContain("warn");
      expect(fig).not.toContain("red");
    }
  });

  test("negative Safety Margin is red, never amber or green", () => {
    const s = baseSnapshot();
    s.safety_margin_weekly = "-0.01";
    const fig = render(s, false).match(/<p data-testid="sm-figure"[^>]*>/)![0];
    expect(fig).toContain("text-red-600");
    expect(fig).not.toContain("warn");
    expect(fig).not.toContain("emerald");
  });

  test("Spendable figure is green at 0.00 and amber when negative", () => {
    const s = baseSnapshot();
    s.left_to_spend_weekly = "0.00";
    const ok = render(s, false).match(/<p data-testid="sp-figure"[^>]*>/)![0];
    expect(ok).toContain("text-emerald-600");
    expect(ok).not.toContain("warn");
    s.left_to_spend_weekly = "-0.01";
    const over = render(s, false).match(/<p data-testid="sp-figure"[^>]*>/)![0];
    expect(over).toContain("text-warn-figure");
    expect(over).not.toContain("emerald");
  });

  test("pending-charges line is shown with count and total", () => {
    const s = baseSnapshot();
    s.pending_cards_count = 2;
    s.pending_cards_total = "87.65";
    const html = render(s, false);
    expect(html).toContain("Includes pending charges on 2 cards ($87.65)");
  });

  test("pending-charges line is masked when hidden and absent at count 0", () => {
    const s = baseSnapshot();
    s.pending_cards_count = 1;
    s.pending_cards_total = "87.65";
    const html = render(s, true);
    expect(html).toContain(`Includes pending charges on 1 card (${BALANCE_MASK})`);
    expect(html).not.toContain("87.65");
    s.pending_cards_count = 0;
    expect(render(s, false)).not.toContain("pending charges");
  });

  test("the sign stays inside the mask on /day lines", () => {
    const hiddenHtml = render(baseSnapshot(), true);
    expect(hiddenHtml).not.toContain("−" + BALANCE_MASK);
    expect(hiddenHtml).toContain(BALANCE_MASK + "/day");
    expect(render(baseSnapshot(), false)).toContain("−$35.77/day");
  });

  test("amber lows use warn-figure; desktop margin figure is 40px", () => {
    const s = baseSnapshot();
    s.lookahead_status = "warning";
    const html = render(s, false);
    expect(html).toContain("text-warn-figure");
    expect(html).not.toMatch(/font-semibold tabular-nums text-warn-text/);
    expect(html.match(/<p data-testid="sm-figure"[^>]*>/)![0]).toContain("md:text-[40px]");
  });

  test("no weekly_lows still renders without a chart", () => {
    const s = baseSnapshot();
    delete s.weekly_lows;
    const html = render(s, false);
    expect(html).toContain("Household Snapshot");
    expect(html).not.toContain("Checking low point each week");
  });
});
