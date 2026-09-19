/* 온누리 가맹점 지도 - 프런트엔드
   멀리서는 시장·상점가가 찍히고, 줌인하면 가맹점 하나하나가 찍힌다.
   가맹점 핀은 식당(주황)과 그 외(회색)로 나뉜다. */

const STORE_LEVEL = 5;   // 이 레벨 이하로 줌인하면 가맹점 핀으로 바뀐다

let map, clusterer, popup;
let storePins = [];
let debounceId = null;
let openMarket = null;   // 상세 보기 중인 시장 id
let selectedStore = null;  // 상세 목록에서 고른 가맹점 id (지도 이동 뒤 다시 그려도 유지)

const storeMode = () => map.getLevel() <= STORE_LEVEL;

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

  // clickable: 지도가 말풍선 위 마우스 이벤트를 가져가면 드래그 핸들러의
  // preventDefault 에 막혀 <a> 의 링크 이동이 죽는다. 네이버 버튼이 안 눌린다.
  popup = new kakao.maps.CustomOverlay({ zIndex: 10, yAnchor: 1.15, clickable: true });

  kakao.maps.event.addListener(map, 'idle', () => schedule(250));
  kakao.maps.event.addListener(map, 'click', () => popup.setMap(null));

  ['q', 'digital', 'food', 'cat'].forEach((id) => {
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
  debounceId = setTimeout(async () => {
    await refresh();
    if (openMarket) await openMarketDetail(openMarket);
  }, delay);
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

/* '지류만 가능한 곳 제외'는 기본이 켜짐이라 filterParams 가 늘 비지 않는다.
   기본 상태와 다를 때만 필터가 걸린 것으로 본다. */
function isFiltered() {
  return Boolean(document.getElementById('q').value.trim())
    || document.getElementById('food').checked
    || Boolean(document.getElementById('cat').value)
    || !document.getElementById('digital').checked;
}

function filterParams() {
  const p = new URLSearchParams();
  const q = document.getElementById('q').value.trim();
  if (q) p.set('q', q);
  if (document.getElementById('digital').checked) p.set('digital', '1');
  if (document.getElementById('food').checked) p.set('food', '1');
  const cat = document.getElementById('cat').value;
  if (cat) p.set('cat', cat);
  return p;
}

/* ---------- 시장 목록 (기본 화면) ---------- */

function bboxParams() {
  const b = map.getBounds();
  const p = filterParams();
  p.set('swLat', b.getSouthWest().getLat());
  p.set('swLng', b.getSouthWest().getLng());
  p.set('neLat', b.getNorthEast().getLat());
  p.set('neLng', b.getNorthEast().getLng());
  return p;
}

const fetchMarkets = () => fetch('/api/markets?' + bboxParams()).then((r) => r.json());
const fetchStores = () => fetch('/api/stores?' + bboxParams()).then((r) => r.json());

/* 지도 레이어. 줌 레벨에 따라 시장 마커와 가맹점 핀을 오간다.
   이미 받아둔 시장 데이터가 있으면 다시 받지 않는다. */
async function drawLayer(marketData) {
  if (storeMode()) {
    clusterer.clear();
    const data = await fetchStores();
    drawStorePins(data.error ? [] : data.points);
    return { mode: 'store', data };
  }
  clearStorePins();
  const data = marketData || await fetchMarkets();
  drawMarkers(data.error ? [] : data.markets);
  return { mode: 'market', data };
}

function storeHint(data) {
  if (data.error) return data.error;
  const shown = data.points.reduce((sum, pt) => sum + pt.stores.length, 0);
  if (shown === 0) return '이 화면에는 위치를 아는 가맹점이 없습니다. 축소하면 시장 단위로 보입니다.';
  const food = data.points.reduce(
    (sum, pt) => sum + pt.stores.filter((s) => s.cat_major === '음식').length, 0);
  return `가맹점 ${shown.toLocaleString()}곳 (식당 ${food.toLocaleString()}곳)`
    + (data.truncated ? ' · 너무 많아 일부만' : '');
}

function marketHint(data) {
  if (data.error) return data.error;
  if (data.markets.length === 0) return '이 화면에는 가맹점이 없습니다. 지도를 옮기거나 검색어를 지워보세요.';
  const stores = data.markets.reduce((sum, m) => sum + m.stores, 0);
  return `이 화면에 시장·상점가 ${data.markets.length.toLocaleString()}곳 · `
    + `가맹점 ${stores.toLocaleString()}곳`
    + (data.truncated ? ' (가맹점 많은 순으로 일부만)' : '')
    + ' · 더 확대하면 가맹점이 하나씩 찍힙니다';
}

async function refresh() {
  const data = await fetchMarkets();
  if (data.error) { setHint(data.error); return; }

  drawMarketList(data.markets);
  const layer = await drawLayer(data);
  setHint(layer.mode === 'store' ? storeHint(layer.data) : marketHint(data));
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
      popup.setMap(null);
      openMarketDetail(m.id);   // 목록에서 고르면 바로 가맹점 목록을 펼친다
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

/* ---------- 가맹점 핀 (줌인했을 때) ---------- */

function clearStorePins() {
  storePins.forEach((pin) => pin.setMap(null));
  storePins = [];
  document.getElementById('legend').hidden = true;
}

function drawStorePins(points) {
  clearStorePins();
  points.forEach((pt) => {
    const foodCount = pt.stores.filter((s) => s.cat_major === '음식').length;
    const el = document.createElement('div');
    el.className = 'spin'
      + (foodCount ? ' food' : '')
      + (pt.stores.length > 1 ? ' many' : '');
    if (pt.stores.length > 1) el.textContent = pt.stores.length;
    el.title = pt.stores.map((s) => s.name).slice(0, 12).join(', ');
    el.addEventListener('click', (e) => { e.stopPropagation(); openStorePopup(pt); });

    const pin = new kakao.maps.CustomOverlay({
      position: new kakao.maps.LatLng(pt.lat, pt.lng),
      content: el, xAnchor: 0.5, yAnchor: 0.5, zIndex: 4,
    });
    pin.setMap(map);
    storePins.push(pin);
  });
  document.getElementById('legend').hidden = storePins.length === 0;
}

/* focused=true 면 목록에서 고른 가게를 제목에 세운다. 한 건물에 수백 곳이 있을 때
   시장 이름만 뜨면 내가 고른 게 어느 것인지 알 수 없다. */
function openStorePopup(pt, focused) {
  const area = pt.sigungu || pt.sido;
  const many = pt.stores.length > 1;
  const el = document.createElement('div');
  el.className = 'pop';
  el.innerHTML =
    `<button class="close" title="닫기">&times;</button>` +
    `<h2>${esc(focused || !many ? pt.stores[0].name : pt.market)}</h2>` +
    `<p>${esc([pt.sido, pt.sigungu].filter(Boolean).join(' '))} · ${esc(pt.market)}` +
    (many ? ` · 이 자리에 ${pt.stores.length}곳` : '') + `</p>` +
    `<ul class="slist">` +
    pt.stores.map((s) =>
      `<li><div class="nm">${esc(s.name)}${badges(s)}` +
      `<div class="cat">${esc(s.cat_name || s.items || '')}</div></div>` +
      `<a class="naver-btn" href="${naverUrl(s.name, area)}" target="_blank" ` +
      `rel="noopener">네이버</a></li>`).join('') +
    `</ul>`;

  el.querySelector('.close').addEventListener('click', () => popup.setMap(null));
  popup.setContent(el);
  popup.setPosition(new kakao.maps.LatLng(pt.lat, pt.lng));
  popup.setMap(map);
}

/* ---------- 시장 상세: 옆으로 펼쳐지는 두 번째 패널 ---------- */

async function openMarketDetail(marketId) {
  const data = await fetch(`/api/markets/${marketId}?` + filterParams()).then((r) => r.json());
  if (data.error) { setHint(data.error); return; }

  if (openMarket !== marketId) selectedStore = null;
  openMarket = marketId;
  const m = data.market;
  const area = m.sigungu || m.sido;

  document.getElementById('detail').hidden = false;
  document.getElementById('detail-name').textContent = m.name;
  document.getElementById('detail-sub').textContent =
    [m.sido, m.sigungu, m.address].filter(Boolean).join(' · ');

  // 뭘 먹을지 고르는 게 목적이라 식당을 위로 올린다.
  const food = data.stores.filter((s) => s.cat_major === '음식');
  const rest = data.stores.filter((s) => s.cat_major !== '음식');
  document.getElementById('detail-count').textContent =
    `가맹점 ${data.stores.length.toLocaleString()}곳`
    + (food.length ? ` · 식당 ${food.length.toLocaleString()}곳` : '')
    + (isFiltered() ? ' (검색·필터 적용됨)' : '');

  // 한 건물에 여러 곳이 있으면 말풍선에 같이 띄워야 한다. 좌표로 묶어둔다.
  const byCoord = new Map();
  data.stores.forEach((s) => {
    if (!s.lat) return;
    const key = s.lat + ',' + s.lng;
    if (!byCoord.has(key)) byCoord.set(key, []);
    byCoord.get(key).push(s);
  });

  const ul = document.getElementById('detail-list');
  ul.innerHTML = '';
  if (data.stores.length === 0) {
    ul.innerHTML = '<li>조건에 맞는 가맹점이 없습니다.</li>';
    return;
  }
  if (food.length) addSection(ul, '식당', 'food');
  food.forEach((s) => ul.appendChild(storeRow(s, m, byCoord)));
  if (rest.length) addSection(ul, food.length ? '그 외' : '가맹점', '');
  rest.forEach((s) => ul.appendChild(storeRow(s, m, byCoord)));
}

function addSection(ul, label, kind) {
  const li = document.createElement('li');
  li.className = 'sect' + (kind ? ' ' + kind : '');
  li.textContent = label;
  ul.appendChild(li);
}

function storeRow(s, m, byCoord) {
  const area = m.sigungu || m.sido;
  const li = document.createElement('li');
  if (s.lat) li.className = 'store' + (s.id === selectedStore ? ' sel' : '');
  li.innerHTML =
    `<div class="row">` +
    `<div><div class="nm">${esc(s.name)}${badges(s)}</div>` +
    (s.cat_name || s.items
      ? `<div class="sub">${esc(s.cat_name || s.items)}</div>` : '') + `</div>` +
    `<a class="naver-btn" href="${naverUrl(s.name, area)}" ` +
    `target="_blank" rel="noopener">네이버</a>` +
    `</div>`;
  if (!s.lat) return li;

  // 좌표를 아는 가게는 지도를 그 자리로 옮기고, 핀을 누른 것과 같은 말풍선을 띄운다.
  li.addEventListener('click', (e) => {
    if (e.target.closest('.naver-btn')) return;
    document.querySelectorAll('#detail-list li.sel').forEach((el) => el.classList.remove('sel'));
    li.classList.add('sel');
    selectedStore = s.id;

    map.setCenter(new kakao.maps.LatLng(s.lat, s.lng));
    if (map.getLevel() > 3) map.setLevel(3);

    // 같은 자리의 가게를 함께 보여주되, 누른 가게를 맨 위로 올린다.
    const here = byCoord.get(s.lat + ',' + s.lng) || [s];
    openStorePopup({
      lat: s.lat, lng: s.lng, market: m.name, sido: m.sido, sigungu: m.sigungu,
      stores: [s].concat(here.filter((x) => x.id !== s.id)),
    }, true);
  });
  return li;
}

function showMarketList() {
  openMarket = null;
  document.getElementById('detail').hidden = true;
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
  document.getElementById('detail').hidden = true;
  map.setLevel(5);
  map.setCenter(new kakao.maps.LatLng(m.lat, m.lng));
}

/* ---------- 공용 ---------- */

function naverUrl(name, area) {
  return 'https://map.naver.com/p/search/' +
    encodeURIComponent(`${name} ${area || ''}`.trim());
}

/* 전 가맹점이 지류를 받고 90.5%가 디지털도 받는다. 둘 다 붙이면 모든 줄에 같은
   뱃지가 달려 아무것도 알려주지 못한다. 드문 쪽인 지류 전용만 짚어준다. */
function badges(s) {
  return s.digital ? '' : '<span class="badge paper-only">지류만</span>';
}

function setHint(text) {
  document.getElementById('hint').textContent = text;
}

function esc(text) {
  return String(text ?? '').replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}
