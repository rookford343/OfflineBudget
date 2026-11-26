import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NeedsAttention } from "./NeedsAttention";
import type { Risk } from "../lib/riskBannerText";

// Made-up fixture amounts only (public repo).
const alertRisk: Risk = {
  at_risk: true,
  date: "2026-12-05",
  amount: "-123.45",
  threshold: "500",
  status: "warning",
};

const g = globalThis as unknown as { localStorage?: Storage };
const original = g.localStorage;

beforeEach(() => {
  g.localStorage = {
    getItem: () => null,
    setItem: () => {},
  } as unknown as Storage;
});

afterEach(() => {
  if (original === undefined) delete g.localStorage;
  else g.localStorage = original;
});

function render(seed: Record<string, unknown[]>, risk: Risk | null) {
  const client = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity, retry: false } },
  });
  const data: Record<string, unknown[]> = {
    "planned-transfers": [],
    "bills-to-confirm": [],
    "amount-drift": [],
    accounts: [],
    ...seed,
  };
  for (const [key, value] of Object.entries(data)) client.setQueryData([key], value);
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <NeedsAttention risk={risk} />
    </QueryClientProvider>,
  );
}

describe("NeedsAttention", () => {
  test("quiet when nothing needs action", () => {
    const html = render({}, null);
    expect(html).toContain("Nothing needs you today.");
    expect(html).not.toContain("Needs attention");
  });

  test("shows items when one has content", () => {
    const html = render(
      {
        "planned-transfers": [
          { id: 1, status: "pending", amount: "250", from_account_id: 1, to_account_id: 2, target_date: "2026-12-04" },
        ],
        accounts: [
          { id: 1, name: "Savings" },
          { id: 2, name: "Checking" },
        ],
      },
      null,
    );
    expect(html).toContain("Needs attention");
    expect(html).not.toContain("Nothing needs you today.");
  });

  test("risk alone counts", () => {
    const html = render({}, alertRisk);
    expect(html).toContain("Needs attention");
    expect(html).not.toContain("Nothing needs you today.");
  });
});
