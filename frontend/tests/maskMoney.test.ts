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
});
