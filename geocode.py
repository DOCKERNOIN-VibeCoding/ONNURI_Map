# -*- coding: utf-8 -*-
"""
주소 → 좌표 변환 (카카오 로컬 API). 중단해도 이어서 실행할 수 있다.

사용법:
    python geocode.py                      # 좌표 없는 전체
    python geocode.py --sido 서울특별시     # 특정 시/도만 (먼저 돌려보기 좋음)
    python geocode.py --limit 500          # 앞 500건만

좌표는 geocache(주소 기준)에 쌓이므로, 재실행해도 이미 변환한 주소는 호출하지 않는다.
"""

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor

import requests

import onnuri_db

ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"
KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"


def lookup(session, headers, address):
    """(lat, lng) 또는 None. 도로명/지번 검색 후 실패하면 상세주소를 떼고 재시도."""
    candidates = [address]
    parts = address.split()
    if len(parts) > 3:
        candidates.append(" ".join(parts[:3]))  # 상세주소(동·호수·건물명) 제거

    for query in candidates:
        for url in (ADDRESS_URL, KEYWORD_URL):
            try:
                res = session.get(url, headers=headers,
                                  params={"query": query, "size": 1}, timeout=10)
            except requests.RequestException:
                continue
            if res.status_code != 200:
                if res.status_code in (401, 403):
                    raise SystemExit(
                        f"카카오 API 인증 실패({res.status_code}). "
                        "config.json 의 kakao_rest_key 와 앱의 '카카오맵' 사용 설정을 확인하세요."
                    )
                continue
            docs = res.json().get("documents") or []
            if docs:
                return float(docs[0]["y"]), float(docs[0]["x"])
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sido", help="시/도 이름으로 대상 제한 (예: 서울특별시)")
    parser.add_argument("--limit", type=int, help="처리할 최대 주소 수")
    parser.add_argument("--workers", type=int, default=4, help="동시 요청 수 (기본 4)")
    args = parser.parse_args()

    config = onnuri_db.load_config()
    headers = {"Authorization": f"KakaoAK {config['kakao_rest_key']}"}

    conn = onnuri_db.init()

    # 좌표가 없고 캐시에도 없는 '고유 주소' 목록
    sql = """
        SELECT DISTINCT s.address FROM stores s
        LEFT JOIN geocache g ON g.address = s.address
        WHERE s.lat IS NULL AND g.address IS NULL
    """
    params = []
    if args.sido:
        sql += " AND s.sido = ?"
        params.append(args.sido)
    if args.limit:
        sql += " LIMIT ?"
        params.append(args.limit)

    targets = [r["address"] for r in conn.execute(sql, params)]
    if not targets:
        apply_cache(conn)
        print("변환할 새 주소가 없습니다.")
        return

    print(f"변환 대상 주소: {len(targets):,}건 (동시 요청 {args.workers})")

    session = requests.Session()
    done = 0
    ok = 0

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for address, result in zip(targets, pool.map(
                lambda a: lookup(session, headers, a), targets)):
            if result:
                conn.execute(
                    "INSERT OR REPLACE INTO geocache VALUES (?, ?, ?, 'ok')",
                    (address, result[0], result[1]))
                ok += 1
            else:
                conn.execute(
                    "INSERT OR REPLACE INTO geocache VALUES (?, NULL, NULL, 'fail')",
                    (address,))
            done += 1
            if done % 50 == 0:
                conn.commit()
                print(f"\r  {done:,}/{len(targets):,}  성공 {ok:,}", end="", flush=True)

    conn.commit()
    print(f"\r  {done:,}/{len(targets):,}  성공 {ok:,}")
    apply_cache(conn)


def apply_cache(conn):
    """geocache 의 좌표를 stores 에 반영."""
    conn.execute("""
        UPDATE stores SET
            lat = (SELECT lat FROM geocache g WHERE g.address = stores.address),
            lng = (SELECT lng FROM geocache g WHERE g.address = stores.address)
        WHERE lat IS NULL
          AND EXISTS (SELECT 1 FROM geocache g
                      WHERE g.address = stores.address AND g.status = 'ok')
    """)
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM stores").fetchone()[0]
    mapped = conn.execute("SELECT COUNT(*) FROM stores WHERE lat IS NOT NULL").fetchone()[0]
    print(f"좌표 확보: {mapped:,} / {total:,}건")


if __name__ == "__main__":
    sys.exit(main())
