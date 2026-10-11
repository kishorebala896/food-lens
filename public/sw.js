// food-lens service worker.
// - app shell: precached, served stale-while-revalidate (instant start, updates next launch)
// - product/alternatives API: network-first, cached copy when offline
// - product images + the ZXing decoder: cache-first
// Bump VERSION when the shell file list changes.

const VERSION = "v1";
const SHELL_CACHE = `fl-shell-${VERSION}`;
const DATA_CACHE = "fl-data";
const ASSET_CACHE = "fl-assets";
const SHELL = [
  "/", "/index.html", "/styles.css", "/app.js", "/scanner.js", "/manifest.webmanifest",
  "/icons/icon-192.png", "/icons/icon-512.png", "/icons/favicon.svg",
];
const MAX_DATA = 60;
const MAX_ASSETS = 150;

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL_CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keep = new Set([SHELL_CACHE, DATA_CACHE, ASSET_CACHE]);
    for (const key of await caches.keys()) if (!keep.has(key)) await caches.delete(key);
    await self.clients.claim();
  })());
});

async function trim(cacheName, max) {
  const cache = await caches.open(cacheName);
  const keys = await cache.keys();
  for (let i = 0; i < keys.length - max; i++) await cache.delete(keys[i]);
}

async function networkFirst(request) {
  const cache = await caches.open(DATA_CACHE);
  try {
    const res = await fetch(request);
    if (res.ok) { cache.put(request, res.clone()); trim(DATA_CACHE, MAX_DATA); }
    return res;
  } catch (err) {
    const hit = await cache.match(request);
    if (hit) return hit;
    throw err;
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(ASSET_CACHE);
  const hit = await cache.match(request);
  if (hit) return hit;
  const res = await fetch(request);
  // opaque (no-cors) image responses report status 0 but are still usable
  if (res.ok || res.type === "opaque") { cache.put(request, res.clone()); trim(ASSET_CACHE, MAX_ASSETS); }
  return res;
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(SHELL_CACHE);
  const hit = await cache.match(request, { ignoreSearch: true });
  const update = fetch(request).then((res) => {
    if (res.ok) cache.put(request, res.clone());
    return res;
  }).catch(() => null);
  return hit || (await update) || Response.error();
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);

  if (url.origin === self.location.origin) {
    if (url.pathname.startsWith("/api/product/") || url.pathname.startsWith("/api/alternatives/")) {
      event.respondWith(networkFirst(request));
    } else if (url.pathname.startsWith("/api/")) {
      return; // search: always live
    } else if (request.mode === "navigate") {
      // SPA: every navigation is the shell (routes live in the hash)
      event.respondWith(fetch(request).catch(async () =>
        (await caches.match("/index.html")) || Response.error()));
    } else {
      event.respondWith(staleWhileRevalidate(request));
    }
    return;
  }

  if (url.hostname === "images.openfoodfacts.org" || url.hostname === "cdn.jsdelivr.net") {
    event.respondWith(cacheFirst(request));
  }
});
