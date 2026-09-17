# -*- coding: utf-8 -*-
"""
시장·상점가의 좌표를 카카오 로컬 API 로 찾는다. (2,700곳 남짓, 몇 분이면 끝난다)

    python geocode_markets.py              # 좌표 없는 곳 전부
    python geocode_markets.py --sido 서울   # 특정 시/도만
    python geocode_markets.py --retry      # 이전에 실패한 곳 재시도

중간에 Ctrl+C 로 끊어도 된다. 다시 실행하면 남은 곳부터 이어서 진행한다.
찾은 도로명 주소에서 시군구를 뽑아 두는데, 네이버 플레이스 검색어에 쓴다.
"""

import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor

import requests

import onnuri_db

KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"


# 전남·광주가 '전남광주통합특별시'로 통합되어, 카카오는 광주 주소도 '전남…'으로 돌려준다.
# 공공데이터는 아직 '광주'와 '전남'을 따로 쓰므로 자치구 이름으로 갈라준다.
GWANGJU_GU = {"동구", "서구", "남구", "북구", "광산구"}


def region_ok(sido, address):
    """카카오가 돌려준 주소가 데이터의 시/도와 같은 지역인지."""
    parts = (address or "").split()
    if not parts:
        return False
    head, sigungu = parts[0], (parts[1] if len(parts) > 1 else "")
    if "광주통합" in head:
        return (sigungu in GWANGJU_GU) if sido == "광주" else (sigungu not in GWANGJU_GU)
    return head.startswith(sido[:2])


SUFFIXES = r"(골목형상점가|지하도상점가|종합상가|상점가|골목시장|먹자골목|전통시장|시장|상가)"


def core_of(name):
    """시장 이름에서 비교용 핵심어. '호남동 골목형상점가' -> '호남동'"""
    bare = re.sub(r"\(.*?\)", "", name).strip()
    trimmed = re.sub(SUFFIXES + r"$", "", bare).strip()
    return (trimmed or bare).split()[0] if (trimmed or bare) else ""


def name_ok(name, place_name, address):
    """카카오가 돌려준 장소가 정말 그 시장인지.

    핵심어가 장소명에도 주소에도 없으면 버린다. '광주 호남동 골목형상점가' 검색에
    엉뚱한 '신가동 골목형상점가'가 걸려 광산구에 찍힌 사례가 있었다.
    상점가 이름이 동 이름인 경우가 많아 주소도 함께 본다. ('일곡동…' -> 북구 일곡동)
    """
    core = core_of(name)
    if len(core) < 2:
        return True
    haystack = ((place_name or "") + (address or "")).replace(" ", "")
    # '동해묵호시장', '천안신부문화거리'처럼 지역명이 앞에 붙은 이름이 많다.
    # 앞 두 글자를 뗀 것도 인정한다. ('동해묵호' -> '묵호')
    cores = [core] + ([core[2:]] if len(core) >= 4 else [])
    return any(c in haystack for c in cores)


def candidates(name, sido):
    """검색어 후보. 원래 이름 → 괄호 제거 → 접미사 제거 순으로 시도한다.

    '목동깨비시장(구 목3동시장)', '흑석시장골목형상점가' 처럼 공공데이터의 시장명에는
    카카오가 모르는 꼬리표가 붙어 있는 경우가 많다.
    """
    variants = [name]
    bare = re.sub(r"\(.*?\)", "", name).strip()
    if bare and bare not in variants:
        variants.append(bare)
    trimmed = re.sub(r"(골목형상점가|지하도상점가|종합상가|상점가|골목시장|먹자골목)$",
                     "", bare or name).strip()
    if trimmed and trimmed not in variants:
        variants.append(trimmed)
    # 시/도를 반드시 붙인다. 이름만으로 찾으면 다른 지역의 동명 시장이 걸린다.
    return [f"{sido} {v}" for v in variants]


def lookup(session, headers, name, sido):
    """(lat, lng, sigungu, address) 또는 None."""
    for query in candidates(name, sido):
        try:
            res = session.get(KEYWORD_URL, headers=headers,
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
        address = doc.get("road_address_name") or doc.get("address_name") or ""
        if not name_ok(name, doc.get("place_name"), address):
            continue
        # 엉뚱한 지역이 걸리는 일이 있다. 시/도가 다르면 버린다.
        # ('서울 영도시장' 검색이 부산 영도시장을 물어온 사례)
        if not region_ok(sido, address):
            continue
        parts = address.split()
        sigungu = parts[1] if len(parts) > 1 else ""
        return float(doc["y"]), float(doc["x"]), sigungu, address

    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sido", help="시/도로 대상 제한 (예: 서울)")
    parser.add_argument("--retry", action="store_true", help="이전 실패분 재시도")
    parser.add_argument("--workers", type=int, default=4, help="동시 요청 수 (기본 4)")
    args = parser.parse_args()

    config = onnuri_db.load_config()
    headers = {"Authorization": "KakaoAK " + config["kakao_rest_key"]}
    conn = onnuri_db.init()

    sql = "SELECT id, name, sido FROM markets WHERE lat IS NULL"
    if not args.retry:
        sql += " AND status IS NULL"
    params = []
    if args.sido:
        sql += " AND sido = ?"
        params.append(args.sido)

    targets = conn.execute(sql, params).fetchall()
    if not targets:
        report(conn)
        print("찾을 시장이 남아있지 않습니다. (--retry 로 실패분을 다시 시도할 수 있습니다)")
        return

    print(f"대상 시장·상점가: {len(targets):,}곳 (동시 요청 {args.workers})")

    session = requests.Session()
    done = ok = 0

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = pool.map(lambda m: lookup(session, headers, m["name"], m["sido"]), targets)
        for market, found in zip(targets, results):
            if found:
                conn.execute(
                    "UPDATE markets SET lat=?, lng=?, sigungu=?, address=?, status='ok' WHERE id=?",
                    (found[0], found[1], found[2], found[3], market["id"]))
                ok += 1
            else:
                conn.execute("UPDATE markets SET status='fail' WHERE id=?", (market["id"],))
            done += 1
            if done % 50 == 0:
                conn.commit()
                print(f"\r  {done:,}/{len(targets):,}  찾음 {ok:,}", end="", flush=True)

    conn.commit()
    print(f"\r  {done:,}/{len(targets):,}  찾음 {ok:,}")
    report(conn)


def report(conn):
    total = conn.execute("SELECT COUNT(*) FROM markets").fetchone()[0]
    mapped = conn.execute("SELECT COUNT(*) FROM markets WHERE lat IS NOT NULL").fetchone()[0]
    covered = conn.execute(
        "SELECT COUNT(*) FROM stores WHERE market_id IN "
        "(SELECT id FROM markets WHERE lat IS NOT NULL)").fetchone()[0]
    stores = conn.execute("SELECT COUNT(*) FROM stores").fetchone()[0]
    print(f"좌표 확보: 시장 {mapped:,}/{total:,}곳 · 가맹점 {covered:,}/{stores:,}곳")


if __name__ == "__main__":
    sys.exit(main())
