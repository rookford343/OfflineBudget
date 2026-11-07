import { describe, expect, test } from "bun:test";
import { maskMoneyText } from "../src/lib/maskMoney";

describe("maskMoneyText", () => {
  test("masks a signed negative amount", () => {
    expect(maskMoneyText(true, "−$400.00 since 7:00 AM")).toBe("•••• since 7:00 AM");
  });
  test("masks a leading plus", () => {
    expect(maskMoneyText(true, "+$50.00")).toBe("••••");
  });
  test("masks every amount in a sentence", () => {
    expect(maskMoneyText(true, "Example Insurance Co. $250.00, Grocery Store $1,100.00"))
      .toBe("Example Insurance Co. ••••, Grocery Store ••••");
  });
  test("returns text unchanged when not hidden", () => {
    const t = "−$400.00 since 7:00 AM";
    expect(maskMoneyText(false, t)).toBe(t);
  });
  test("leaves times and versions alone", () => {
    expect(maskMoneyText(true, "7:00 AM")).toBe("7:00 AM");
    expect(maskMoneyText(true, "v12")).toBe("v12");
  });
  test("masks the Month in Review narrative forms", () => {
    expect(maskMoneyText(true, "You spent $5,000.00 in total, ($20,000.00 less) than planned and $72.94 more than May."))
      .toBe("You spent •••• in total, (•••• less) than planned and •••• more than May.");
  });
  test("masks a bare whole-dollar and a parenthesised amount alone", () => {
    expect(maskMoneyText(true, "($20,000.00 less)")).toBe("(•••• less)");
    expect(maskMoneyText(true, "$72.94 more")).toBe("•••• more");
    expect(maskMoneyText(true, "$5,000.00")).toBe("••••");
  });
  test("leaves percentages visible", () => {
    expect(maskMoneyText(true, "up 12.5% vs last month")).toBe("up 12.5% vs last month");
  });
});
