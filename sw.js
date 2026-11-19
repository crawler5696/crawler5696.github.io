/* 뉴스레이더 — 오프라인에서도 마지막으로 본 뉴스를 보여주는 최소 서비스워커
   네트워크 우선(network-first): 항상 최신을 먼저 받고, 실패했을 때만 캐시를 쓴다.
   캐시가 먼저 나갔다가 네트워크로 덮어쓰는 방식이 아니므로 화면이 두 번 그려지지 않는다.
   data/news.json 은 쿼리스트링(?_=타임스탬프)까지 포함해 언제나 네트워크를 먼저 탄다 —
   새로고침(⟳) 때 캐시가 섞여 들어오지 않도록 cache:'no-store' 로 요청한다. */
const CACHE = 'newsradar-v33';
const SHELL = ['./', './index.html', './manifest.json', './icons/icon-192.png', './data/calendar.json', './data/radar.json'];
const NEWS_KEY = './data/news.json';   // 쿼리스트링이 붙어도 캐시에는 이 한 자리에만 남긴다

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

const isNewsJson = url => /\/data\/news\.json$/.test(url.pathname);
const isCalJson = url => /\/data\/calendar\.json$/.test(url.pathname);
const isRadarJson = url => /\/data\/radar\.json$/.test(url.pathname);
const isHotJson = url => /\/data\/hotbar\.json$/.test(url.pathname);
const isSchedJson = url => /\/data\/schedule\.json$/.test(url.pathname);
const CAL_KEY = './data/calendar.json';
const RADAR_KEY = './data/radar.json';
const HOT_KEY = './data/hotbar.json';
const SCHED_KEY = './data/schedule.json';

/* 캐시에서 꺼낸 응답에는 표시(x-news-cache)를 붙인다.
   화면은 이 표시를 보면 "새로고침 실패(저장본 표시)"로 알린다 — 오래된 데이터를 최신이라고 말하지 않기 위해. */
async function markCached(res){
  try{
    const h = new Headers(res.headers);
    h.set('x-news-cache', '1');
    h.delete('content-length');
    h.delete('content-encoding');
    return new Response(await res.blob(), {status: res.status, statusText: res.statusText, headers: h});
  }catch(e){ return res; }
}

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  const news = isNewsJson(url);
  const cal = isCalJson(url);
  const rdr = isRadarJson(url);
  const hot = isHotJson(url);
  const sch = isSchedJson(url);

  e.respondWith((async () => {
    try {
      // 뉴스 데이터는 쿼리스트링과 무관하게 항상 네트워크가 먼저(그리고 캐시 협상 없이)
      const fresh = await fetch(req, {cache: (news || cal || rdr || hot || sch) ? 'no-store' : (req.mode === 'navigate' ? 'no-store' : 'no-cache')});
      if (fresh && fresh.ok && (fresh.type === 'basic' || fresh.type === 'default')) {
        const copy = fresh.clone();
        const key = news ? NEWS_KEY : (cal ? CAL_KEY : (rdr ? RADAR_KEY : (hot ? HOT_KEY : (sch ? SCHED_KEY : req))));   // 데이터 파일은 한 자리에만 저장(매번 다른 ?_= 주소로 쌓이지 않게)
        caches.open(CACHE).then(c => c.put(key, copy)).catch(() => {});
      }
      return fresh;
    } catch (err) {
      const hit = await caches.match(req, {ignoreSearch: true});
      if (hit) return news ? await markCached(hit) : hit;
      if (req.mode === 'navigate') {
        const shell = await caches.match('./index.html', {ignoreSearch: true});
        if (shell) return shell;
      }
      throw err;
    }
  })());
});
