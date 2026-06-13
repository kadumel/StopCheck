const CACHE = 'stopcheck-static-v2';
const STATIC_ASSETS = ['/static/icons/icon-192.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(STATIC_ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  if (e.request.method !== 'GET') return;

  const url = new URL(e.request.url);
  if (url.pathname.startsWith('/motorista')) {
    e.respondWith(fetch(e.request));
    return;
  }

  if (!url.pathname.startsWith('/static/')) return;

  e.respondWith(
    caches.match(e.request).then((cached) => {
      const network = fetch(e.request).then((response) => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE).then((cache) => cache.put(e.request, clone));
        }
        return response;
      });
      return cached || network;
    })
  );
});
