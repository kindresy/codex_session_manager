const CACHE_NAME = "codex-sessions-shell-v1";
const APP_SHELL = ["/", "/index.html", "/app.css", "/app.js", "/manifest.webmanifest", "/icon.svg"];
const APP_PATHS = new Set(APP_SHELL);

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((names) => Promise.all(names.filter((name) => name !== CACHE_NAME).map((name) => caches.delete(name)))),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.pathname === "/api" || url.pathname.startsWith("/api/")) return;
  if (event.request.method !== "GET" || url.origin !== self.location.origin || !APP_PATHS.has(url.pathname)) return;
  event.respondWith(caches.match(event.request).then((cached) => cached || fetch(event.request)));
});
