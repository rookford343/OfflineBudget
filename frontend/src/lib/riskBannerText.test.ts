import { describe, expect, test } from "bun:test";
import {
  alertHeadline,
  projectedBalanceText,
  suggestionHeadline,
  transferHeadline,
} from "./riskBannerText";

// Made-up fixture amounts only (public repo).
const THRESHOLD = "500";
const AMOUNT = "-123.45";
const TRANSFER = "750";
const SUGGESTED = "600";
const MASK = "••••••";
const LEAKS = ["123.45", "750.00", "600.00", "500.00"];

function expectMasked(text: string) {
  expect(text).not.toContain("$");
  for (const leak of LEAKS) expect(text).not.toContain(leak);
  expect(text).toContain(MASK);
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
