/* Noyob agent planshet katalogi — offline service worker.
   Agent ofisda Wi-Fi'da "Offline yuklash" tugmasini bosadi: barcha rasm va
   ma'lumot keshga tushadi. Keyin supermarketda internetsiz to'liq ishlaydi. */
const CACHE = 'noyob-planshet-v1';
const SHELL = ['./', './index.html', './manifest.json', './katalog.json'];

self.addEventListener('install', e => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).catch(() => {}));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;

  // rasmlar: keshdan (o'zgarmaydi)
  if (url.pathname.includes('/rasm/')) {
    e.respondWith(
      caches.match(req).then(r => r || fetch(req).then(res => {
        if (res.ok) { const c = res.clone(); caches.open(CACHE).then(x => x.put(req, c)); }
        return res;
      }).catch(() => new Response('', {status: 404})))
    );
    return;
  }

  // qolgani: avval tarmoq, uzilsa kesh
  e.respondWith(
    fetch(req).then(res => {
      if (res.ok) { const c = res.clone(); caches.open(CACHE).then(x => x.put(req, c)); }
      return res;
    }).catch(() => caches.match(req).then(r => r || caches.match('./index.html')))
  );
});

/* Ommaviy keshlash — sahifadan {tur:'HAMMASI', royxat:[...]} kelganda */
self.addEventListener('message', async e => {
  const d = e.data || {};
  if (d.tur !== 'HAMMASI') return;
  const port = e.ports && e.ports[0];
  const c = await caches.open(CACHE);
  const royxat = d.royxat || [];
  let tayyor = 0, xato = 0;
  const PARTIYA = 8;

  for (let i = 0; i < royxat.length; i += PARTIYA) {
    await Promise.all(royxat.slice(i, i + PARTIYA).map(async u => {
      try {
        if (await c.match(u)) { tayyor++; return; }
        const r = await fetch(u, {cache: 'reload'});
        if (r.ok) { await c.put(u, r); tayyor++; } else xato++;
      } catch (_) { xato++; }
    }));
    if (port) port.postMessage({tayyor, xato, jami: royxat.length});
  }
  if (port) port.postMessage({tayyor, xato, jami: royxat.length, tugadi: true});
});
