// Harpua2001 Service Worker — offline-first caching
// Strategy:
//   - Static HTML pages: network-first with cache fallback (so updates land fast)
//   - Same-origin assets (/items/*.html, banner.jpg, manifest): stale-while-revalidate
//   - eBay images (i.ebayimg.com): cache-first with quiet refresh in background
//   - CDN libs (cdn.jsdelivr.net, fonts.googleapis.com): cache-first
//   - Lambda API calls (jw0hur2091.execute-api...): network-only, never cached

const VERSION    = 'h2k-v2-pwa';
const STATIC_CACHE  = `${VERSION}-static`;
const RUNTIME_CACHE = `${VERSION}-runtime`;
const IMG_CACHE     = `${VERSION}-img`;

const PRECACHE = [
  './',
  'index.html',
  'quality.html',
  'price_review.html',
  'title_review.html',
  'reddit.html',
  'craigslist.html',
  'return-policy.html',
  'manifest.webmanifest',
  'banner.jpg',
  'store_logo_512.png',
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(STATIC_CACHE)
      .then(c => c.addAll(PRECACHE).catch(() => null))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys
        .filter(k => !k.startsWith(VERSION))
        .map(k => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);

  // Never cache the lambda API
  if (url.hostname.endsWith('amazonaws.com')) return;
  // Don't cache POSTs
  if (e.request.method !== 'GET') return;

  // eBay product images — cache-first (they don't change)
  if (url.hostname === 'i.ebayimg.com') {
    e.respondWith(cacheFirst(e.request, IMG_CACHE));
    return;
  }

  // CDN libraries (versioned URLs, safe to cache aggressively)
  if (url.hostname === 'cdn.jsdelivr.net' || url.hostname === 'fonts.googleapis.com' || url.hostname === 'fonts.gstatic.com') {
    e.respondWith(cacheFirst(e.request, RUNTIME_CACHE));
    return;
  }

  // Same-origin images — cache-first (logos, banners, og-card, etc.)
  if (url.origin === self.location.origin && /\.(png|jpe?g|gif|svg|webp|ico)$/i.test(url.pathname)) {
    e.respondWith(cacheFirst(e.request, IMG_CACHE));
    return;
  }

  // Same-origin HTML & everything else — network-first (fresh content wins, fall back to cache offline)
  if (url.origin === self.location.origin) {
    e.respondWith(networkFirst(e.request, STATIC_CACHE));
    return;
  }
});

async function cacheFirst(req, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(req);
  if (cached) {
    // Refresh in background, ignore failures
    fetch(req).then(r => r && r.ok && cache.put(req, r)).catch(() => {});
    return cached;
  }
  try {
    const fresh = await fetch(req);
    if (fresh && fresh.ok) cache.put(req, fresh.clone());
    return fresh;
  } catch (e) {
    return new Response('offline', { status: 503 });
  }
}

async function networkFirst(req, cacheName) {
  const cache = await caches.open(cacheName);
  try {
    const fresh = await fetch(req);
    if (fresh && fresh.ok) cache.put(req, fresh.clone());
    return fresh;
  } catch (e) {
    const cached = await cache.match(req);
    if (cached) return cached;
    // Last resort: return cached homepage
    return cache.match('index.html') || new Response('offline', { status: 503 });
  }
}
