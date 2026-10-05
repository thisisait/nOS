// nOS: GeoLibre's own service worker is replaced by this one, which removes
// itself. Behind forward_auth a cached app shell hid an expired sign-in: the
// page loaded, every request then hit the Authentik redirect (2026-10-04).
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    await self.registration.unregister();
    for (const name of await caches.keys()) await caches.delete(name);
    for (const client of await self.clients.matchAll({ type: "window" })) client.navigate(client.url);
  })());
});
