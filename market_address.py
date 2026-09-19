# -*- coding: utf-8 -*-
"""
공식 시장·상점가 목록으로 주소를 채우고, 그 주소로 좌표를 찍는다.

    python market_address.py              # 주소 매칭 + 좌표 찾기
    python market_address.py --match-only # 주소만 채우고 좌표는 나중에

온누리 가맹점 CSV 에는 주소가 없지만(소재지가 '서울' 같은 시/도 한 단어다),
소상공인시장진흥공단이 전통시장·골목형상점가·상점가 현황을 따로 공개하고 있고
거기에는 주소가 들어있다. 이름으로 맞춰 주소를 가져오고, 주소 검색으로 좌표를 구한다.
이름만 검색하는 geocode_markets.py 보다 정확하다.

전통시장만 쓰면 골목형상점가·상점가가 통째로 빠진다. 실제로 그래서 지도에서
'○○음식문화거리' 같은 곳이 안 보였다. 그래서 세 가지를 모두 본다.
이 스크립트가 좌표를 채운 시장은 status 가 'official' 이 되고,
geocode_markets.py 는 lat 이 비어있는 것만 보므로 서로 건드리지 않는다.
"""

import argparse
import csv
import io
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

import requests

import fetch_data
import geocode_markets
import onnuri_db

# 전통시장은 2025년판이 최신이지만 2015년판에만 있는 시장이 100곳 남짓 된다. 둘 다 본다.
# 골목형상점가·상점가는 전통시장 목록에 없어서 따로 받아야 한다.
DATASETS = [
    ("https://www.data.go.kr/data/15052837/fileData.do", "전통시장현황_2025.csv"),
    ("https://www.data.go.kr/data/15118622/fileData.do", "골목형상점가현황.csv"),
    ("https://www.data.go.kr/data/15118623/fileData.do", "상점가현황.csv"),
    ("https://www.data.go.kr/data/15052836/fileData.do", "전통시장현황_2015.csv"),
]

ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"
REGION_URL = "https://dapi.kakao.com/v2/local/geo/coord2regioncode.json"

# 온누리상품권 공식 사이트(www.onnuri.gift/place)가 시장 목록을 좌표까지 공개한다.
# 공공데이터 현황자료에 없는 상권활성화구역·지하상가까지 들어있어 빈 곳을 메우는 데 쓴다.
ONNURI_MARKET_URL = "https://www.onnuri.gift/api/v3/onrgt/place/market"

# 2015년판에는 시/도 컬럼이 없어 주소 앞머리에서 뽑아야 한다.
SIDO_OF_FULL = {
    "서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천",
    "광주광역시": "광주", "대전광역시": "대전", "울산광역시": "울산", "세종특별자치시": "세종",
    "경기도": "경기", "강원도": "강원", "강원특별자치도": "강원",
    "충청북도": "충북", "충청남도": "충남",
    "전라북도": "전북", "전북특별자치도": "전북", "전라남도": "전남",
    "경상북도": "경북", "경상남도": "경남",
    "제주도": "제주", "제주특별자치도": "제주",
}


def read_csv(content):
    """공공데이터 CSV 는 회차마다 인코딩이 다르다."""
    for encoding in ("cp949", "utf-8-sig", "utf-8"):
        try:
            text = content.decode(encoding)
        except UnicodeDecodeError:
            continue
        return list(csv.DictReader(io.StringIO(text)))
    raise SystemExit("CSV 인코딩을 알 수 없습니다.")


def key_of(name, sido):
    """비교용 키. 괄호 안 설명과 공백을 지운 이름 + 시/도."""
    return re.sub(r"\s+", "", re.sub(r"\(.*?\)", "", name or "")).strip(), sido


def sido_of(address):
    parts = (address or "").split()
    if not parts:
        return ""
    return SIDO_OF_FULL.get(parts[0], parts[0][:2])


def official_rows(rows):
    """데이터셋마다 다른 컬럼 이름을 (키, 도로명주소, 지번주소, 시군구) 로 통일한다.

    전통시장현황은 도로명/지번이 나뉘어 있고, 골목형상점가·상점가는 '주소' 하나뿐이다.
    """
    for row in rows:
        name = row.get("시장명", "")
        road = (row.get("도로명주소") or row.get("소재지도로명주소")
                or row.get("주소") or "").strip()
        jibun = (row.get("지번주소") or row.get("소재지지번주소") or "").strip()
        sido = (row.get("시도") or "").strip() or sido_of(road or jibun)
        sigungu = (row.get("시군구") or "").strip()
        if not name or not (road or jibun):
            continue
        yield key_of(name, sido), road, jibun, sigungu


def load_official(session, save_dir):
    """공식 목록들을 받아 키 -> (도로명주소, 지번주소, 시군구) 로 만든다.

    먼저 넣은 쪽이 이긴다. DATASETS 순서가 곧 우선순위다.
    """
    table = {}
    for dataset_url, fallback in DATASETS:
        print(f"내려받는 중: {fallback}")
        _, content = fetch_data.download(session, dataset_url, fallback)
        with open(os.path.join(save_dir, fallback), "wb") as f:
            f.write(content)
        rows = read_csv(content)
        added = 0
        for key, road, jibun, sigungu in official_rows(rows):
            if key not in table:
                table[key] = (road, jibun, sigungu)
                added += 1
        print(f"  {len(rows):,}행 → 새로 얻은 시장 {added:,}곳")
    return table


def match(conn, table):
    """markets 에 공식 주소를 채우고, 채워진 수를 돌려준다."""
    filled = 0
    for market in conn.execute("SELECT id, name, sido FROM markets").fetchall():
        found = table.get(key_of(market["name"], market["sido"]))
        if not found:
            continue
        road, jibun, _ = found
        conn.execute("UPDATE markets SET official_addr = ? WHERE id = ?",
                     (road or jibun, market["id"]))
        filled += 1
    conn.commit()
    return filled


def lookup(session, headers, address):
    """주소 -> (lat, lng, sigungu, address). 못 찾으면 None."""
    for query in (address, re.sub(r"\(.*?\)", "", address).strip()):
        try:
            res = session.get(ADDRESS_URL, headers=headers,
                              params={"query": query, "size": 1}, timeout=10)
        except requests.RequestException:
            continue

        if res.status_code in (401, 403):
            raise SystemExit(
                f"카카오 API 인증 실패({res.status_code}). config.json 의 kakao_rest_key 와 "
                "카카오 개발자 사이트의 '카카오맵' 사용 설정을 확인하세요."
            )
        if res.status_code != 200:
            continue

        docs = res.json().get("documents") or []
        if not docs:
            continue

        doc = docs[0]
        road = (doc.get("road_address") or {}).get("address_name")
        found = road or (doc.get("address") or {}).get("address_name") or query
        parts = found.split()
        return float(doc["y"]), float(doc["x"]), (parts[1] if len(parts) > 1 else ""), found

    return None


def geocode(conn, workers):
    """공식 주소는 있는데 아직 주소 기반 좌표가 아닌 시장을 처리한다."""
    targets = conn.execute(
        "SELECT id, name, official_addr FROM markets "
        "WHERE official_addr IS NOT NULL AND (status IS NULL OR status != 'official')"
    ).fetchall()
    if not targets:
        print("주소로 좌표를 찍을 시장이 남아있지 않습니다.")
        return

    config = onnuri_db.load_config()
    headers = {"Authorization": "KakaoAK " + config["kakao_rest_key"]}
    print(f"주소로 좌표 찾기: {len(targets):,}곳 (동시 요청 {workers})")

    session = requests.Session()
    done = ok = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = pool.map(lambda m: lookup(session, headers, m["official_addr"]), targets)
        for market, found in zip(targets, results):
            if found:
                conn.execute(
                    "UPDATE markets SET lat=?, lng=?, sigungu=?, address=?, status='official' "
                    "WHERE id=?",
                    (found[0], found[1], found[2], found[3], market["id"]))
                ok += 1
            done += 1
            if done % 50 == 0:
                conn.commit()
                print(f"\r  {done:,}/{len(targets):,}  찾음 {ok:,}", end="", flush=True)

    conn.commit()
    print(f"\r  {done:,}/{len(targets):,}  찾음 {ok:,}")


def onnuri_markets(session):
    """공식 사이트의 시장 목록. 이름 -> [(lat, lng)]."""
    res = session.post(ONNURI_MARKET_URL, json={},
                       headers={"Content-Type": "application/json",
                                "Origin": "https://www.onnuri.gift",
                                "Referer": "https://www.onnuri.gift/place"}, timeout=60)
    res.raise_for_status()
    body = res.json()
    if body.get("resCode") != "0000":
        raise SystemExit(f"공식 사이트 응답 오류: {body.get('resMsg')}")

    table = {}
    for row in body["data"]["list"]:
        if not row.get("latitude"):
            continue
        key = re.sub(r"\s+", "", re.sub(r"\(.*?\)", "", row["frcsNm"] or "")).strip()
        table.setdefault(key, []).append((row["latitude"], row["longitude"]))
    return table


def region_of(session, headers, lat, lng):
    """좌표가 실제로 어느 시/도인지. 이름만으로 맞춘 것을 검증하는 용도."""
    try:
        res = session.get(REGION_URL, headers=headers,
                          params={"x": lng, "y": lat}, timeout=10)
    except requests.RequestException:
        return None, None
    if res.status_code != 200:
        return None, None
    docs = [d for d in (res.json().get("documents") or []) if d.get("region_type") == "H"]         or (res.json().get("documents") or [])
    if not docs:
        return None, None
    return docs[0].get("region_1depth_name", ""), docs[0].get("region_2depth_name", "")


def sido_matches(want, region_sido, region_sigungu):
    """역조회된 행정구역이 우리 데이터의 시/도와 같은 지역인지.

    카카오는 광주도 전남도 '전남광주통합특별시'로 돌려준다. 자치구 이름으로 갈라야 한다.
    geocode_markets 가 같은 문제를 이미 풀어놨으므로 그 목록을 그대로 쓴다.

    '충청남도'는 '충남'으로 시작하지 않는다. 앞 두 글자 비교로는 충남·충북·경남·경북을
    전부 놓치므로 반드시 SIDO_OF_FULL 로 약칭을 구해서 비교한다.
    """
    if "광주통합" in (region_sido or ""):
        in_gwangju = region_sigungu in geocode_markets.GWANGJU_GU
        return in_gwangju if want == "광주" else not in_gwangju
    return sido_of(region_sido) == want


def fill_from_onnuri(conn, workers):
    """공공데이터로도 못 찾은 시장을 공식 사이트 좌표로 메운다.

    응답에 시/도가 없어 이름으로만 맞춰야 한다. 그래서 좌표의 행정구역을 되짚어
    우리 데이터의 시/도와 같은지 확인하고, 다르면 버린다.
    """
    targets = conn.execute(
        "SELECT id, name, sido FROM markets WHERE lat IS NULL").fetchall()
    if not targets:
        return

    session = requests.Session()
    session.headers.update({"User-Agent": fetch_data.UA})
    print("공식 사이트(onnuri.gift) 시장 목록 확인 중…")
    table = onnuri_markets(session)
    print(f"  좌표가 있는 시장 {len(table):,}곳")

    config = onnuri_db.load_config()
    headers = {"Authorization": "KakaoAK " + config["kakao_rest_key"]}

    candidates = []
    for market in targets:
        key = re.sub(r"\s+", "", re.sub(r"\(.*?\)", "", market["name"])).strip()
        spots = table.get(key)
        if spots:
            candidates.append((market, spots))
    if not candidates:
        print("  이름이 맞는 시장이 없습니다.")
        return

    print(f"  이름이 맞은 시장 {len(candidates):,}곳 — 좌표의 시/도를 확인합니다")
    placed = rejected = 0

    def verify(item):
        market, spots = item
        for lat, lng in spots:
            sido, sigungu = region_of(session, headers, lat, lng)
            if sido and sido_matches(market["sido"], sido, sigungu):
                return market, lat, lng, sigungu
        return market, None, None, None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for market, lat, lng, sigungu in pool.map(verify, candidates):
            if lat is None:
                rejected += 1
                continue
            conn.execute(
                "UPDATE markets SET lat=?, lng=?, sigungu=?, status='onnuri' WHERE id=?",
                (lat, lng, sigungu, market["id"]))
            placed += 1
    conn.commit()
    print(f"  좌표를 얻음 {placed:,}곳 · 시/도가 달라 버림 {rejected:,}곳")


def report(conn):
    one = lambda sql: conn.execute(sql).fetchone()[0]
    total = one("SELECT COUNT(*) FROM markets")
    mapped = one("SELECT COUNT(*) FROM markets WHERE lat IS NOT NULL")
    official = one("SELECT COUNT(*) FROM markets WHERE status IN ('official', 'onnuri')")
    stores = one("SELECT COUNT(*) FROM stores")
    covered = one("SELECT COUNT(*) FROM stores WHERE market_id IN "
                  "(SELECT id FROM markets WHERE lat IS NOT NULL)")
    print(f"좌표 확보: 시장 {mapped:,}/{total:,}곳 (공식 주소 기반 {official:,}곳) · "
          f"가맹점 {covered:,}/{stores:,}곳")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-only", action="store_true",
                        help="공식 주소만 채우고 좌표는 찾지 않는다")
    parser.add_argument("--workers", type=int, default=4, help="동시 요청 수 (기본 4)")
    args = parser.parse_args()

    conn = onnuri_db.init()
    data_dir = os.path.join(onnuri_db.BASE_DIR, "data")
    os.makedirs(data_dir, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": fetch_data.UA})

    table = load_official(session, data_dir)
    print(f"공식 시장 목록: {len(table):,}곳")

    filled = match(conn, table)
    print(f"우리 시장과 이름이 맞은 곳: {filled:,}곳")

    if not args.match_only:
        geocode(conn, args.workers)
        fill_from_onnuri(conn, args.workers)
    report(conn)


if __name__ == "__main__":
    sys.exit(main())
