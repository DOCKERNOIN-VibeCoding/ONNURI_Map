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
import sys
from concurrent.futures import ThreadPoolExecutor

import requests

import onnuri_db

KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"


def lookup(session, headers, name, sido):
    """(lat, lng, sigungu, address) 또는 None."""
    # 시/도를 붙여야 같은 이름의 다른 지역 시장으로 가지 않는다
    for query in (f"{sido} {name}", name):
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
