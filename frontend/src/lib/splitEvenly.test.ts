import { describe, expect, test } from "bun:test";
import { splitEvenly } from "./splitEvenly";

describe("splitEvenly", () => {
  test("divides evenly with no remainder", () => {
    expect(splitEvenly(90, 3)).toEqual([30, 30, 30]);
  });

  test("puts the extra cents on the first legs, summing to the exact total", () => {
    const result = splitEvenly(100, 3);
    expect(result).toEqual([33.34, 33.33, 33.33]);
    expect(result.reduce((a, b) => a + b, 0)).toBeCloseTo(100, 2);
  });

  test("single leg returns the whole total", () => {
    expect(splitEvenly(42.5, 1)).toEqual([42.5]);
  });
});
