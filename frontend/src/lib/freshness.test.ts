import { describe, expect, test } from "bun:test";
import { summarizePending, lastBankSync } from "./freshness";

describe("summarizePending", () => {
  test("counts cards with a non-zero pending amount, skipping inactive ones", () => {
    expect(
      summarizePending([
        { pending_effective: "86.00" },
        { pending_effective: "0" },
        { pending_effective: null },
        { is_active: false, pending_effective: "10" },
      ]),
    ).toEqual({ count: 1, total: 86 });
  });

  test("empty list is zero", () => {
    expect(summarizePending([])).toEqual({ count: 0, total: 0 });
  });

  test("sums several cards and accepts numbers", () => {
    expect(summarizePending([{ pending_effective: 12.5 }, { pending_effective: "7.5" }])).toEqual({ count: 2, total: 20 });
  });
});

describe("lastBankSync", () => {
  const live = { status: "ok", links: [{ is_active: true }] };
  test("none when no live connection has pulled", () => {
    expect(lastBankSync([])).toBeNull();
    expect(lastBankSync([{ ...live, last_success_at: null }])).toBeNull();
  });
  test("ignores disconnected and takes the newest", () => {
    const d = lastBankSync([
      { ...live, last_success_at: "2026-11-06T10:00:00Z" },
      { ...live, last_success_at: "2026-11-07T10:00:00Z" },
      { status: "disconnected", links: [{ is_active: true }], last_success_at: "2026-11-08T10:00:00Z" },
    ]);
    expect(d?.toISOString()).toBe("2026-11-07T10:00:00.000Z");
  });
});
