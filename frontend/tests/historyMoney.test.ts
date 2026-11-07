import { describe, expect, test } from "bun:test";
import { itemMoney, signedMoney } from "../src/lib/historyMoney";

describe("history money display", () => {
  test("hidden mode masks item and signed amounts", () => {
    expect(itemMoney(true, "250.00")).not.toMatch(/\d/);
    expect(signedMoney(true, "-400.00", true)).not.toMatch(/\d/);
  });
  test("visible mode shows them", () => {
    expect(itemMoney(false, "1234.50")).toBe("$1,234.50");
    expect(signedMoney(false, "-400.00", true)).toBe("−$400.00");
    expect(signedMoney(false, "12.50", true)).toBe("+$12.50");
  });
});
