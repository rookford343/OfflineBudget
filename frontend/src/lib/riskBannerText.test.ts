import { describe, expect, test } from "bun:test";
import {
  alertHeadline,
  effectiveTransferAmount,
  projectedBalanceText,
  riskHasContent,
  type Risk,
  suggestionHeadline,
  transferHeadline,
} from "./riskBannerText";

// Made-up fixture amounts only (public repo).
const THRESHOLD = "500";
const AMOUNT = "-123.45";
const BIG = "1234.00";
const TRANSFER = "750";
const SUGGESTED = "600";
const MASK = "••••••";
const LEAKS = ["123.45", "750.00", "600.00", "500.00", "123", "750", "600", "500", "1,234", "1234"];

function expectMasked(text: string) {
  expect(text).not.toContain("$");
  for (const leak of LEAKS) expect(text).not.toContain(leak);
  expect(text).toContain(MASK);
  // Dates carry digits, so strip them before asserting no amount digits remain.
  expect(text.replace(/(January|February|March|April|May|June|July|August|September|October|November|December) \d+/g, "")).not.toMatch(/\d/);
}

describe("RiskBanner text masks every amount when balances are hidden", () => {
  test("transferHeadline", () => {
    expectMasked(transferHeadline(TRANSFER, "Savings", "2026-12-05", true));
    expect(transferHeadline(TRANSFER, "Savings", "2026-12-05", false)).toBe(
      "Needs a $750.00 transfer from Savings around December 5",
    );
  });

  test("suggestionHeadline, already planned", () => {
    expectMasked(suggestionHeadline(SUGGESTED, "2026-12-05", true, true));
    expect(suggestionHeadline(SUGGESTED, "2026-12-05", true, false)).toBe(
      "Still short: top up by $600.00 by December 5",
    );
  });

  test("suggestionHeadline, new suggestion", () => {
    expectMasked(suggestionHeadline(SUGGESTED, "2026-12-05", false, true));
    expect(suggestionHeadline(SUGGESTED, "2026-12-05", false, false)).toBe(
      "Suggested: move $600.00 to cover this by December 5",
    );
  });

  test("alertHeadline, warning", () => {
    expectMasked(alertHeadline(THRESHOLD, "warning", "2026-12-05", true));
    expect(alertHeadline(THRESHOLD, "warning", "2026-12-05", false)).toBe(
      "Projected to drop below your $500.00 cushion on December 5",
    );
  });

  test("alertHeadline, danger", () => {
    expectMasked(alertHeadline(THRESHOLD, "danger", "2026-12-05", true));
    expect(alertHeadline(THRESHOLD, "danger", "2026-12-05", false)).toBe(
      "Drops below your $500.00 cushion on December 5 and goes negative within the window",
    );
  });

  test("alertHeadline, negative threshold has no amount to leak", () => {
    const hiddenText = alertHeadline("0", "danger", "2026-12-05", true);
    expect(hiddenText).not.toContain("$");
    expect(hiddenText).toBe("Projected to go negative on December 5");
    expect(alertHeadline("0", "danger", "2026-12-05", false)).toBe(hiddenText);
  });

  test("projectedBalanceText", () => {
    expectMasked(projectedBalanceText(AMOUNT, true));
    expect(projectedBalanceText(AMOUNT, false)).toBe("-$123.45");
  });
});

describe("thousands-separator amounts are masked", () => {
  test("transferHeadline and suggestionHeadline", () => {
    expectMasked(transferHeadline(BIG, "Savings", "2026-12-05", true));
    expectMasked(suggestionHeadline(BIG, "2026-12-05", false, true));
    expect(transferHeadline(BIG, "Savings", "2026-12-05", false)).toContain("$1,234.00");
  });
});

describe("amount-only text carries no digits when hidden", () => {
  test("projectedBalanceText", () => {
    expect(projectedBalanceText(AMOUNT, true)).not.toMatch(/\d/);
    expect(projectedBalanceText(BIG, true)).not.toMatch(/\d/);
    expect(projectedBalanceText(BIG, true)).toBe(MASK);
  });
});

describe("riskHasContent", () => {
  const base: Risk = { at_risk: false, date: null, amount: null, threshold: THRESHOLD };

  test("false for null, undefined and an empty risk", () => {
    expect(riskHasContent(null)).toBe(false);
    expect(riskHasContent(undefined)).toBe(false);
    expect(riskHasContent(base)).toBe(false);
  });

  test("true for an alert", () => {
    expect(riskHasContent({ ...base, at_risk: true, date: "2026-12-05", amount: AMOUNT })).toBe(true);
  });

  test("true for a triggered transfer", () => {
    expect(
      riskHasContent({ ...base, transfer_triggered: true, transfer_date: "2026-12-05", transfer_amount: TRANSFER }),
    ).toBe(true);
  });

  test("true for a suggestion", () => {
    expect(
      riskHasContent({
        ...base,
        at_risk: true,
        suggested_transfer_amount: SUGGESTED,
        suggested_transfer_date: "2026-12-05",
      }),
    ).toBe(true);
  });
});

describe("effectiveTransferAmount", () => {
  test("hidden ignores the override", () => {
    expect(effectiveTransferAmount(true, "999", "600.00")).toBe("600.00");
    expect(effectiveTransferAmount(true, "999", null)).toBe("");
  });

  test("visible prefers the override, then the suggestion", () => {
    expect(effectiveTransferAmount(false, "999", "600.00")).toBe("999");
    expect(effectiveTransferAmount(false, "", "600.00")).toBe("600.00");
    expect(effectiveTransferAmount(false, "", undefined)).toBe("");
  });
});
