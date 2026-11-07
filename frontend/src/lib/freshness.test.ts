import { describe, expect, test } from "bun:test";
import { lastBankSync } from "./freshness";

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
