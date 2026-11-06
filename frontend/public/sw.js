// Keeps the app shell available on patchy networks. API responses hold family data and are never cached.
const CACHE = "entitled-v2";
// The on-device document and speech readers keep their models in their own caches (public/ocr/worker.js and
// public/speech/worker.js). A download of 40 MB is never thrown away here.
const KEEP = (key) => key === CACHE || key.startsWith("entitled-ocr-") || key.startsWith("entitled-speech-");
const SHELL = ["/", "/manifest.webmanifest", "/icons/icon-192.png", "/icons/icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => !KEEP(key)).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/portal/")) return;

  // /ort/ holds ONNX Runtime, versioned with the app's dependencies, so reading on the device also works offline.
  if (url.pathname.startsWith("/_next/static/") || url.pathname.startsWith("/icons/") || url.pathname.startsWith("/ort/")) {
    event.respondWith(
      caches.match(event.request).then((hit) => hit || fetch(event.request).then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(event.request, copy));
        }
        return response;
      })),
    );
    return;
  }
  if (event.request.mode === "navigate") {
    event.respondWith(fetch(event.request).catch(() => caches.match("/")));
  }
});
