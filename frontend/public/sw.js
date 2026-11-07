// Hand-written service worker: caches the app shell only, never API data.
// CACHE_VERSION: bump by hand when this file's behaviour changes. Cached
// shell files need no bump per release: they are stale-while-revalidate, and
// Vite's hashed /assets/* names change with every build, so a new build
// brings new files (and the new index.html on the next load).
importScripts("/sw-policy.js");

const CACHE_VERSION = "1";
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

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);

  if (self.cacheStrategy(url, self.location.origin) === "app-shell") {
    event.respondWith(
      caches.open(CACHE).then(async (cache) => {
        const cached = await cache.match(req);
        const refresh = fetch(req)
          .then((res) => {
            if (res.ok) cache.put(req, res.clone());
            return res;
          })
          .catch(() => undefined);
        return cached || (await refresh) || Response.error();
      }),
    );
    return;
  }

  // Client-route navigations: network first, cached index.html when offline.
  // The page itself then shows the "can't reach your Mac" banner.
  if (req.mode === "navigate" && !url.pathname.startsWith("/api/")) {
    event.respondWith(
      fetch(req).catch(async () => (await caches.match("/index.html")) || Response.error()),
    );
  }
  // Everything else (including /api): not intercepted, so never stored.
});
