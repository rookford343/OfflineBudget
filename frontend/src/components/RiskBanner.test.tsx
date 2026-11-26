import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RiskBanner } from "./RiskBanner";
import { BALANCE_MASK } from "../store/balanceVisibility";
import type { Risk } from "../lib/riskBannerText";

// Made-up fixture amounts only (public repo).
const risk: Risk = {
  at_risk: true,
  date: "2026-12-05",
  amount: "-123.45",
  threshold: "500",
  status: "warning",
  suggested_transfer_amount: "600.00",
  suggested_transfer_date: "2026-12-04",
  suggested_transfer_from_account_id: 7,
};

// balanceVisibility.ts reads hidden state from localStorage ("budget_balances_hidden").
// Bun has no localStorage, so stub a minimal one and restore afterwards.
const g = globalThis as unknown as { localStorage?: Storage };
const original = g.localStorage;

beforeEach(() => {
  const store = new Map<string, string>([["budget_balances_hidden", "1"]]);
  g.localStorage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
  } as unknown as Storage;
});

afterEach(() => {
  if (original === undefined) delete g.localStorage;
  else g.localStorage = original;
});

function render() {
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <RiskBanner risk={risk} onAcceptSuggestion={() => {}} />
    </QueryClientProvider>,
  );
}

describe("RiskBanner while balances are hidden", () => {
  test("masks the amount, shows the hint, and leaks no fixture amount", () => {
    const html = render();
    // Tailwind classes such as amber-500 contain digits that are not amounts.
    const content = html.replace(/ class="[^"]*"/g, "");
    expect(html).toContain(BALANCE_MASK);
    // Visible text, not just a title tooltip.
    expect(html).toMatch(/>[^<]*Show balances to edit the amount[^<]*</);
    for (const leak of ["123.45", "123", "600", "500"]) expect(content).not.toContain(leak);
  });

  test("renders no amount input (the date input stays)", () => {
    const html = render();
    expect(html).not.toContain('type="number"');
    expect(html).toContain('type="date"');
  });
});
