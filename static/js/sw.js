/* ═══════════════════════════════════════════════════════════════════════
   J.A.R.V.I.S. service worker
   Makes the terminal installable + usable on flaky mobile networks.

   Strategy:
     • App shell (HTML/CSS/JS/icons)  → cache-first, refreshed in background.
     • API calls (/api/*)             → network-first, fall back to last
                                         cached response when offline.
   ═══════════════════════════════════════════════════════════════════════ */
const VERSION = "jarvis-v21";
const SHELL = `${VERSION}-shell`;
const DATA = `${VERSION}-data`;

const SHELL_ASSETS = [
  "/",
  "/static/css/terminal.css",
  "/static/js/terminal.js",
  "/static/js/globe.js",
  "/static/js/brain.js",
  "/static/js/device.js",
  "/static/manifest.webmanifest",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL).then((c) => c.addAll(SHELL_ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => !k.startsWith(VERSION)).map((k) => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);

  // Only manage same-origin requests. Cross-origin (map tiles, MapLibre/Tesseract
  // CDNs, fonts) must bypass the worker entirely.
  if (url.origin !== self.location.origin) return;

  // Never cache the streaming endpoints.
  if (url.pathname.startsWith("/api/chat") || url.pathname.startsWith("/api/agents/stream")) return;

  // API: network-first with cache fallback.
  if (url.pathname.startsWith("/api/")) {
    event.respondWith(
      fetch(request)
        .then((resp) => {
          const copy = resp.clone();
          caches.open(DATA).then((c) => c.put(request, copy));
          return resp;
        })
        .catch(() => caches.match(request))
    );
    return;
  }

  // App shell + navigations: cache-first, revalidate in background.
  event.respondWith(
    caches.match(request).then((cached) => {
      const network = fetch(request)
        .then((resp) => {
          if (resp && resp.ok) {
            const copy = resp.clone();
            caches.open(SHELL).then((c) => c.put(request, copy));
          }
          return resp;
        })
        .catch(() => cached);
      return cached || network;
    })
  );
});
