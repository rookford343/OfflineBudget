import { test, expect } from "bun:test";
import { readFileSync } from "node:fs";

const ORIGIN = "https://mac.local";
const g = globalThis as any;
const handlers: Record<string, (e: any) => void> = {};
const store = new Map<string, any>();
const puts: string[] = [];
let network: (url: string) => Promise<any> = async () => { throw new Error("offline"); };

const keyOf = (r: any) => new URL(typeof r === "string" ? r : r.url, ORIGIN).href;
const cache = {
  match: async (r: any) => store.get(keyOf(r)),
  put: async (r: any, res: any) => { puts.push(new URL(keyOf(r)).pathname); store.set(keyOf(r), res); },
  keys: async () => [...store.keys()].map((u) => ({ url: u })),
  delete: async (r: any) => store.delete(keyOf(r)),
  addAll: async () => {},
};
g.self = g;
g.location = new URL(ORIGIN);
g.caches = { open: async () => cache, match: async (r: any) => store.get(keyOf(r)), keys: async () => ["ob-shell-v1"], delete: async () => true };
g.fetch = (r: any) => network(keyOf(r));
g.addEventListener = (name: string, fn: any) => { handlers[name] = fn; };
g.importScripts = () => (0, eval)(readFileSync("public/sw-policy.js", "utf8"));
(0, eval)(readFileSync("public/sw.js", "utf8"));

const reply = (body: string, type: string) =>
  new Response(body, { status: 200, headers: { "content-type": type } });

async function dispatch(path: string, mode = "cors") {
  let responded: Promise<any> | undefined;
  const waits: Promise<any>[] = [];
  handlers.fetch({
    request: { url: ORIGIN + path, method: "GET", mode },
    respondWith: (p: any) => { responded = Promise.resolve(p); },
    waitUntil: (p: Promise<any>) => waits.push(p),
  });
  const res = responded ? await responded : undefined;
  await Promise.all(waits);
  return res;
}

test("api and cross-origin requests are never stored", async () => {
  puts.length = 0;
  network = async () => reply("{}", "application/json");
  expect(await dispatch("/api/accounts")).toBeUndefined();
  let responded = false;
  handlers.fetch({
    request: { url: "https://evil.example/assets/x.js", method: "GET", mode: "cors" },
    respondWith: () => { responded = true; },
    waitUntil: () => {},
  });
  expect(responded).toBe(false);
  expect(puts).toEqual([]);
});

test("an html response for a missing asset is not stored", async () => {
  puts.length = 0;
  store.clear();
  network = async () => reply("<html>SPA</html>", "text/html");
  await dispatch("/assets/x.js");
  expect(puts).toEqual([]);
});

test("navigation offline falls back to cached index.html", async () => {
  store.clear();
  store.set(ORIGIN + "/index.html", reply("<html>shell</html>", "text/html"));
  network = async () => { throw new Error("offline"); };
  const res = await dispatch("/dashboard", "navigate");
  expect(await res.text()).toBe("<html>shell</html>");
});

test("a changed index.html clears stale cached assets", async () => {
  store.clear();
  store.set(ORIGIN + "/", reply("old", "text/html"));
  store.set(ORIGIN + "/assets/old-1.js", reply("x", "text/javascript"));
  network = async () => reply("new", "text/html");
  await dispatch("/", "navigate");
  expect([...store.keys()]).toEqual([ORIGIN + "/"]);
});
