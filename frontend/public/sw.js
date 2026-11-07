// Hand-written service worker: caches the app shell only, never API data.
// CACHE_VERSION: bump by hand when this file's behaviour changes. Per-release
// freshness needs no bump: the shell is stale-while-revalidate (always
// re-fetched with cache:"no-cache"), Vite's hashed /assets/* names change with
// every build, and when index.html changes the whole shell cache is cleared so
// old hashed files don't pile up.
importScripts("/sw-policy.js");

const CACHE_VERSION = "1";
// A navigation that hasn't answered by then falls back to the cached shell, so
// a phone off the home network opens the app (and its banner) instead of hanging.
const NAV_TIMEOUT_MS = self.OB_NAV_TIMEOUT_MS || 8000;
const CACHE = "ob-shell-v" + CACHE_VERSION;
const PRECACHE = ["/", "/index.html", "/manifest.webmanifest", "/icons/icon-192.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith("ob-shell-") && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

function isIndex(url) {
  return url.pathname === "/" || url.pathname === "/index.html";
}

async function refreshShell(cache, req, url, cached) {
  const res = await fetch(req, { cache: "no-cache" }).catch(() => undefined);
  if (!res || !res.ok) return res;
  const type = (res.headers && res.headers.get("content-type")) || "";
  // A missing asset can come back as the SPA's index.html; never store that
  // under a script/style/icon URL.
  if (type.includes("text/html") && req.mode !== "navigate" && !isIndex(url)) return res;
  if (isIndex(url) && cached) {
    const [oldText, newText] = await Promise.all([cached.clone().text(), res.clone().text()]);
    if (oldText !== newText) {
      for (const key of await cache.keys()) await cache.delete(key);
    }
  }
  await cache.put(req, res.clone());
  return res;
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);

  if (self.cacheStrategy(url, self.location.origin) === "app-shell") {
    event.respondWith(
      caches.open(CACHE).then(async (cache) => {
        const cached = await cache.match(req);
        const refresh = refreshShell(cache, req, url, cached);
        event.waitUntil(refresh.catch(() => undefined));
        return cached || (await refresh) || Response.error();
      }),
    );
    return;
  }

  // Client-route navigations: network first, cached index.html when offline.
  // The page itself then shows the "can't reach your Mac" banner.
  if (req.mode === "navigate" && !url.pathname.startsWith("/api/")) {
    event.respondWith(
      (async () => {
        const network = fetch(req).catch(() => undefined);
        const timer = new Promise((resolve) => setTimeout(() => resolve(undefined), NAV_TIMEOUT_MS));
        const res = await Promise.race([network, timer]);
        if (res) return res;
        // Offline or too slow: the cached shell, else keep waiting on the network.
        return (await caches.match("/index.html")) || (await network) || Response.error();
      })(),
    );
  }
  // Everything else (including /api): not intercepted, so never stored.
});
