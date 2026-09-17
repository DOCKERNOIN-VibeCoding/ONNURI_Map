/* 온누리 가맹점 지도 - 프런트엔드 */

const MARKER_LEVEL = 8;   // 이보다 축소하면 마커 대신 건수만 안내 (카카오는 숫자가 클수록 축소)

let map, clusterer, popup;
let debounceId;

kakao.maps.load(() => {
  map = new kakao.maps.Map(document.getElementById('map'), {
    center: new kakao.maps.LatLng(37.5703, 126.9997),  // 광장시장 부근
    level: 6,
  });
  map.addControl(new kakao.maps.ZoomControl(), kakao.maps.ControlPosition.RIGHT);

  clusterer = new kakao.maps.MarkerClusterer({
    map, averageCenter: true, minLevel: 5, gridSize: 70,
  });
  kakao.maps.event.addListener(clusterer, 'clusterclick', (cluster) => {
    map.setLevel(map.getLevel() - 2, { anchor: cluster.getCenter() });
  });

  popup = new kakao.maps.CustomOverlay({ zIndex: 10, yAnchor: 1.15 });

  kakao.maps.event.addListener(map, 'idle', () => {
    clearTimeout(debounceId);
    debounceId = setTimeout(refresh, 250);
  });
  kakao.maps.event.addListener(map, 'click', () => popup.setMap(null));

  ['q', 'paper', 'digital'].forEach((id) => {
    document.getElementById(id).addEventListener('input', () => {
      clearTimeout(debounceId);
      debounceId = setTimeout(refresh, 300);
    });
  });
  document.getElementById('q').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') jumpToFirstMatch();
  });

  loadStats();
  refresh();
});

async function loadStats() {
  const s = await fetch('/api/stats').then((r) => r.json());
  const el = document.getElementById('stats');
  el.textContent = s.total === 0
    ? '데이터가 없습니다. import_csv.py 를 먼저 실행하세요.'
    : `전체 ${s.total.toLocaleString()}곳 · 좌표 확보 ${s.mapped.toLocaleString()}곳`;
}

function currentQuery() {
  const p = new URLSearchParams();
  const q = document.getElementById('q').value.trim();
  if (q) p.set('q', q);
  if (document.getElementById('paper').checked) p.set('paper', '1');
  if (document.getElementById('digital').checked) p.set('digital', '1');
  return p;
}

async function refresh() {
  const hint = document.getElementById('hint');

  if (map.getLevel() > MARKER_LEVEL) {
    clusterer.clear();
    popup.setMap(null);
    document.getElementById('list').innerHTML = '';
    hint.textContent = '지도를 확대하면 가맹점이 표시됩니다.';
    return;
  }

  const b = map.getBounds();
  const p = currentQuery();
  p.set('swLat', b.getSouthWest().getLat());
  p.set('swLng', b.getSouthWest().getLng());
  p.set('neLat', b.getNorthEast().getLat());
  p.set('neLng', b.getNorthEast().getLng());

  const data = await fetch('/api/stores?' + p).then((r) => r.json());
  if (data.error) { hint.textContent = data.error; return; }

  hint.textContent = data.truncated
    ? `이 화면에 ${data.total.toLocaleString()}곳 (많아서 ${data.stores.length.toLocaleString()}곳만 표시)`
    : `이 화면에 ${data.total.toLocaleString()}곳`;

  drawMarkers(data.stores);
  drawList(data.stores);
}

function drawMarkers(stores) {
  clusterer.clear();
  clusterer.addMarkers(stores.map((s) => {
    const marker = new kakao.maps.Marker({
      position: new kakao.maps.LatLng(s.lat, s.lng),
      title: s.name,
    });
    kakao.maps.event.addListener(marker, 'click', () => openPopup(s));
    return marker;
  }));
}

function drawList(stores) {
  const ul = document.getElementById('list');
  ul.innerHTML = '';
  stores.slice(0, 200).forEach((s) => {
    const li = document.createElement('li');
    const sub = [s.market, s.items].filter(Boolean).map(esc).join(' · ');
    li.innerHTML =
      `<div class="nm">${esc(s.name)}${badges(s)}</div>` +
      (sub ? `<div class="sub">${sub}</div>` : '') +
      `<div class="sub">${esc(s.address)}</div>`;
    li.addEventListener('click', () => {
      map.setCenter(new kakao.maps.LatLng(s.lat, s.lng));
      if (map.getLevel() > 4) map.setLevel(4);
      openPopup(s);
    });
    ul.appendChild(li);
  });
}

function badges(s) {
  return (s.paper ? '<span class="badge p">지류</span>' : '') +
         (s.digital ? '<span class="badge d">디지털</span>' : '');
}

function openPopup(s) {
  const naverUrl = 'https://map.naver.com/p/search/' +
    encodeURIComponent(`${s.name} ${s.sigungu || ''}`.trim());

  const el = document.createElement('div');
  el.className = 'pop';
  el.innerHTML =
    `<button class="close" title="닫기">&times;</button>` +
    `<h2>${esc(s.name)}${badges(s)}</h2>` +
    (s.market ? `<p>${esc(s.market)}</p>` : '') +
    `<p>${esc(s.address)}</p>` +
    (s.items ? `<p>취급품목: ${esc(s.items)}</p>` : '') +
    `<div class="acts">` +
    `<a class="naver" href="${naverUrl}" target="_blank" rel="noopener">네이버 플레이스</a>` +
    `<button class="copy">주소 복사</button>` +
    `</div>`;

  el.querySelector('.close').addEventListener('click', () => popup.setMap(null));
  el.querySelector('.copy').addEventListener('click', (e) => {
    navigator.clipboard.writeText(s.address);
    e.target.textContent = '복사됨';
  });

  popup.setContent(el);
  popup.setPosition(new kakao.maps.LatLng(s.lat, s.lng));
  popup.setMap(map);
}

async function jumpToFirstMatch() {
  const q = document.getElementById('q').value.trim();
  if (!q) return;
  const data = await fetch('/api/search?q=' + encodeURIComponent(q)).then((r) => r.json());
  if (!data.stores.length) {
    document.getElementById('hint').textContent = `'${q}' 검색 결과가 없습니다.`;
    return;
  }
  const s = data.stores[0];
  map.setLevel(5);
  map.setCenter(new kakao.maps.LatLng(s.lat, s.lng));
}

function esc(text) {
  return String(text ?? '').replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}
