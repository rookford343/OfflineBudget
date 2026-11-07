// Classic script shared by sw.js (importScripts) and the unit tests.
// Decides what the service worker may store. Only the app shell is cached;
// every API response, cross-origin request and client route is network-only.
self.cacheStrategy = function cacheStrategy(url, scopeOrigin) {
  if (url.origin !== scopeOrigin) return "network-only";
  const p = url.pathname;
  if (p === "/" || p === "/index.html" || p === "/manifest.webmanifest") return "app-shell";
  if (p.startsWith("/assets/") || p.startsWith("/icons/")) return "app-shell";
  return "network-only";
};
