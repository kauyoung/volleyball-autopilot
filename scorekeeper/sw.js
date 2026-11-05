// Volleyball Autopilot scorekeeper: offline copy, so the page reopens with no signal in the gym.
// The page itself: try the internet first (so a new version shows up right away), but give up after
// 3 seconds and use the copy kept on the phone. Logo, icons and font: the kept copy, refreshed now and then.
// Uploads to Google Drive never go through here.
const CACHE = 'vbap-v1';   // change the number when the logo, icons or font change
const PAGE = './';
const FILES = ['./', 'favicon.svg', 'favicon-32.png', 'apple-touch-icon.png', 'icon-192.png', 'icon-512.png',
               'inter-latin.woff2', 'manifest.webmanifest'];

self.addEventListener('install', e => {
  // one by one, so a single missing file can't stop the rest from being kept
  e.waitUntil(caches.open(CACHE).then(c => Promise.allSettled(FILES.map(f => c.add(f)))).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

function fromNetwork(req, ms) {
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error('slow')), ms);
    fetch(req).then(r => { clearTimeout(t); resolve(r); }, err => { clearTimeout(t); reject(err); });
  });
}

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  // the scorekeeper page (also when it is called volleyball-scorekeeper.html, as on GitHub); other pages: normal internet
  const isPage = req.mode === 'navigate' && (url.pathname.endsWith('/') || /scorekeeper\.html$|\/index\.html$/.test(url.pathname));
  if (isPage) {
    e.respondWith((async () => {
      const cache = await caches.open(CACHE);
      try {
        const res = await fromNetwork(new Request(req.url, { cache: 'no-cache' }), 3000);   // always ask the site (cheap if unchanged)
        if (res.ok) cache.put(PAGE, res.clone());
        return res;
      } catch (err) {
        return (await cache.match(PAGE)) || Response.error();
      }
    })());
    return;
  }
  if (!FILES.includes(url.pathname.replace(/^\//, ''))) return;   // anything else: normal internet
  e.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const kept = await cache.match(req, { ignoreSearch: true });
    const fresh = fetch(req).then(r => { if (r.ok) cache.put(req, r.clone()); return r; }).catch(() => null);
    return kept || (await fresh) || Response.error();
  })());
});
