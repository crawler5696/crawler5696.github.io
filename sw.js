/* 증시 뉴스 레이더 — 오프라인에서도 마지막으로 본 뉴스를 보여주는 최소 서비스워커
   네트워크 우선(network-first): 항상 최신을 먼저 받고, 실패했을 때만 캐시를 쓴다.
   캐시가 먼저 나갔다가 네트워크로 덮어쓰는 방식이 아니므로 화면이 두 번 그려지지 않는다. */
const CACHE = 'newsradar-v3';
const SHELL = ['./', './index.html', './manifest.json', './icons/icon-192.png'];

self.addEventListener('install', e => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).catch(() => {}));
});

self.addEventListener('activate', e => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  e.respondWith((async () => {
    try {
      const fresh = await fetch(req, {cache: req.mode === 'navigate' ? 'no-store' : 'no-cache'});
      if (fresh && fresh.ok && (fresh.type === 'basic' || fresh.type === 'default')) {
        const copy = fresh.clone();
        caches.open(CACHE).then(c => c.put(req, copy)).catch(() => {});
      }
      return fresh;
    } catch (err) {
      const hit = await caches.match(req, {ignoreSearch: true});
      if (hit) return hit;
      if (req.mode === 'navigate') {
        const shell = await caches.match('./index.html', {ignoreSearch: true});
        if (shell) return shell;
      }
      throw err;
    }
  })());
});
