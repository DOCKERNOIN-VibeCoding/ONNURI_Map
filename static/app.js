/* 온누리 가맹점 지도 - 프런트엔드
   지도에 찍히는 것은 시장·상점가. 핀을 누르면 그 안의 가맹점 목록이 왼쪽에 뜬다. */

let map, clusterer, popup;
let debounceId = null;
let openMarket = null;   // 상세 보기 중인 시장 id

kakao.maps.load(() => {
  map = new kakao.maps.Map(document.getElementById('map'), {
    center: new kakao.maps.LatLng(36.5, 127.8),   // 전국이 보이는 위치
    level: 13,
  });
  map.addControl(new kakao.maps.ZoomControl(), kakao.maps.ControlPosition.RIGHT);

  clusterer = new kakao.maps.MarkerClusterer({
    map, averageCenter: true, minLevel: 7, gridSize: 70,
  });
  kakao.maps.event.addListener(clusterer, 'clusterclick', (cluster) => {
    map.setLevel(map.getLevel() - 2, { anchor: cluster.getCenter() });
  });

  popup = new kakao.maps.CustomOverlay({ zIndex: 10, yAnchor: 1.15 });

  kakao.maps.event.addListener(map, 'idle', () => schedule(250));
  kakao.maps.event.addListener(map, 'click', () => popup.setMap(null));

  ['q', 'paper', 'digital'].forEach((id) => {
    document.getElementById(id).addEventListener('input', () => schedule(300));
  });
  document.getElementById('q').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') jumpToFirstMatch();
  });
  document.getElementById('back').addEventListener('click', showMarketList);

  loadStats();
  refresh();
});

function schedule(delay) {
  clearTimeout(debounceId);
  debounceId = setTimeout(() => (openMarket ? openMarketDetail(openMarket) : refresh()), delay);
}

async function loadStats() {
  const s = await fetch('/api/stats').then((r) => r.json());
  const el = document.getElementById('stats');
  if (s.markets === 0) {
    el.textContent = '데이터가 없습니다. fetch_data.py 를 먼저 실행하세요.';
  } else if (s.mapped === 0) {
    el.textContent = '시장 좌표가 없습니다. geocode_markets.py 를 먼저 실행하세요.';
  } else {
    el.textContent = `시장·상점가 ${s.mapped.toLocaleString()}곳 · 가맹점 ${s.stores.toLocaleString()}곳`;
  }
}

function filterParams() {
  const p = new URLSearchParams();
  const q = document.getElementById('q').value.trim();
  if (q) p.set('q', q);
  if (document.getElementById('paper').checked) p.set('paper', '1');
  if (document.getElementById('digital').checked) p.set('digital', '1');
  return p;
}

/* ---------- 시장 목록 (기본 화면) ---------- */

async function refresh() {
  const b = map.getBounds();
  const p = filterParams();
  p.set('swLat', b.getSouthWest().getLat());
  p.set('swLng', b.getSouthWest().getLng());
  p.set('neLat', b.getNorthEast().getLat());
  p.set('neLng', b.getNorthEast().getLng());

  const data = await fetch('/api/markets?' + p).then((r) => r.json());
  if (data.error) { setHint(data.error); return; }

  const markets = data.markets;
  const stores = markets.reduce((sum, m) => sum + m.stores, 0);
  setHint(markets.length === 0
    ? '이 화면에는 가맹점이 없습니다. 지도를 옮기거나 검색어를 지워보세요.'
    : `이 화면에 시장·상점가 ${markets.length.toLocaleString()}곳 · 가맹점 ${stores.toLocaleString()}곳`
      + (data.truncated ? ' (가맹점 많은 순으로 일부만)' : ''));

  drawMarkers(markets);
  drawMarketList(markets);
}

function drawMarkers(markets) {
  clusterer.clear();
  clusterer.addMarkers(markets.map((m) => {
    const marker = new kakao.maps.Marker({
      position: new kakao.maps.LatLng(m.lat, m.lng),
      title: `${m.name} (${m.stores})`,
    });
    kakao.maps.event.addListener(marker, 'click', () => openPopup(m));
    return marker;
  }));
}

function drawMarketList(markets) {
  const ul = document.getElementById('list');
  ul.innerHTML = '';
  markets.forEach((m) => {
    const li = document.createElement('li');
    li.className = 'market';
    li.innerHTML =
      `<div class="row">` +
      `<div><div class="nm">${esc(m.name)}</div>` +
      `<div class="sub">${esc([m.sido, m.sigungu].filter(Boolean).join(' '))}</div></div>` +
      `<span class="count">${m.stores.toLocaleString()}곳</span>` +
      `</div>`;
    li.addEventListener('click', () => {
      map.setCenter(new kakao.maps.LatLng(m.lat, m.lng));
      if (map.getLevel() > 5) map.setLevel(5);
      openPopup(m);
    });
    ul.appendChild(li);
  });
}

function openPopup(m) {
  const el = document.createElement('div');
  el.className = 'pop';
  el.innerHTML =
    `<button class="close" title="닫기">&times;</button>` +
    `<h2>${esc(m.name)}</h2>` +
    `<p>${esc([m.sido, m.sigungu].filter(Boolean).join(' '))}</p>` +
    (m.address ? `<p>${esc(m.address)}</p>` : '') +
    `<p><b>온누리 가맹점 ${m.stores.toLocaleString()}곳</b></p>` +
    `<div class="acts">` +
    `<button class="open">가맹점 보기</button>` +
    `<a href="${naverUrl(m.name, m.sigungu || m.sido)}" target="_blank" rel="noopener">네이버 지도</a>` +
    `</div>`;

  el.querySelector('.close').addEventListener('click', () => popup.setMap(null));
  el.querySelector('.open').addEventListener('click', () => openMarketDetail(m.id));

  popup.setContent(el);
  popup.setPosition(new kakao.maps.LatLng(m.lat, m.lng));
  popup.setMap(map);
}

/* ---------- 시장 상세: 가맹점 목록 ---------- */

async function openMarketDetail(marketId) {
  const data = await fetch(`/api/markets/${marketId}?` + filterParams()).then((r) => r.json());
  if (data.error) { setHint(data.error); return; }

  openMarket = marketId;
  const m = data.market;

  document.getElementById('detail-head').hidden = false;
  document.getElementById('detail-name').textContent = m.name;
  document.getElementById('detail-sub').textContent =
    [m.sido, m.sigungu, m.address].filter(Boolean).join(' · ');
  setHint(`가맹점 ${data.stores.length.toLocaleString()}곳`
    + (filterParams().toString() ? ' (검색·필터 적용됨)' : ''));

  const ul = document.getElementById('list');
  ul.innerHTML = '';
  data.stores.forEach((s) => {
    const li = document.createElement('li');
    li.innerHTML =
      `<div class="row">` +
      `<div><div class="nm">${esc(s.name)}${badges(s)}</div>` +
      (s.items ? `<div class="sub">${esc(s.items)}</div>` : '') + `</div>` +
      `<a class="naver-btn" href="${naverUrl(s.name, m.sigungu || m.sido)}" ` +
      `target="_blank" rel="noopener">네이버</a>` +
      `</div>`;
    ul.appendChild(li);
  });
}

function showMarketList() {
  openMarket = null;
  document.getElementById('detail-head').hidden = true;
  popup.setMap(null);
  refresh();
}

/* ---------- 검색 ---------- */

async function jumpToFirstMatch() {
  const q = document.getElementById('q').value.trim();
  if (!q) return;
  const data = await fetch('/api/search?q=' + encodeURIComponent(q)).then((r) => r.json());
  if (!data.markets.length) {
    setHint(`'${q}' 검색 결과가 없습니다.`);
    return;
  }
  const m = data.markets[0];
  openMarket = null;
  document.getElementById('detail-head').hidden = true;
  map.setLevel(5);
  map.setCenter(new kakao.maps.LatLng(m.lat, m.lng));
}

/* ---------- 공용 ---------- */

function naverUrl(name, area) {
  return 'https://map.naver.com/p/search/' +
    encodeURIComponent(`${name} ${area || ''}`.trim());
}

function badges(s) {
  return (s.paper ? '<span class="badge p">지류</span>' : '') +
         (s.digital ? '<span class="badge d">디지털</span>' : '');
}

function setHint(text) {
  document.getElementById('hint').textContent = text;
}

function esc(text) {
  return String(text ?? '').replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}
