import { test, expect } from "bun:test";

(globalThis as any).self = globalThis;
await import("../../public/sw-policy.js");
const strategy = (globalThis as any).cacheStrategy as (u: URL, origin: string) => string;
const ORIGIN = "https://df-macbookpro16.local";
const s = (p: string) => strategy(new URL(p, ORIGIN), ORIGIN);

test("api responses are never cached", () => {
  expect(s("/api/spending/budget-snapshot?account_id=1")).toBe("network-only");
  expect(s("/api/health")).toBe("network-only");
});
test("app shell files are cached", () => {
  expect(s("/assets/index-abc.js")).toBe("app-shell");
  expect(s("/")).toBe("app-shell");
  expect(s("/index.html")).toBe("app-shell");
  expect(s("/icons/icon-192.png")).toBe("app-shell");
  expect(s("/manifest.webmanifest")).toBe("app-shell");
});
test("cross-origin and client routes are network-only", () => {
  expect(s("https://evil.example/assets/x.js")).toBe("network-only");
  expect(s("/dashboard")).toBe("network-only");
});
