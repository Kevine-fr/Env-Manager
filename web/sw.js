/* =========================================================================
   ENV Manager — Service Worker
   Met en cache UNIQUEMENT la coquille statique (HTML/CSS/JS/icônes).
   Les routes /api/* (qui transportent les secrets) ne sont JAMAIS interceptées
   ni mises en cache. Incrémentez CACHE pour forcer une mise à jour.
   ========================================================================= */
const CACHE = "envmgr-shell-v11";

const SHELL = [
  "/",
  "/index.html",
  "/styles.css",
  "/app.js",
  "/infra.js",
  "/manifest.json",
  "/icons/mark.png",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/apple-touch-icon.png",
  "/icons/favicon-32.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Ne jamais toucher : requêtes non-GET, cross-origin, ou l'API (secrets).
  if (req.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/")) {
    return; // laisse le navigateur faire sa requête réseau normale
  }

  // Navigations : réseau d'abord, repli sur la coquille en cache (mode hors-ligne).
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put("/", copy));
          return res;
        })
        .catch(() => caches.match("/").then((r) => r || caches.match("/index.html")))
    );
    return;
  }

  // Icônes / images / polices : changent rarement → cache d'abord.
  if (/\.(png|jpe?g|svg|gif|ico|webp|woff2?)$/i.test(url.pathname)) {
    event.respondWith(
      caches.match(req).then((cached) =>
        cached ||
        fetch(req).then((res) => {
          if (res && res.status === 200) {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(req, copy));
          }
          return res;
        })
      )
    );
    return;
  }

  // Coquille HTML/CSS/JS : réseau d'abord pour toujours refléter le dernier
  // déploiement, repli sur le cache uniquement hors-ligne.
  event.respondWith(
    fetch(req)
      .then((res) => {
        if (res && res.status === 200) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return res;
      })
      .catch(() => caches.match(req))
  );
});
