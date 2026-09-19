# -*- coding: utf-8 -*-
"""
상가(상권)정보로 가맹점 하나하나의 좌표를 찾는다.

    python store_coords.py                 # 내려받고 전국 매칭
    python store_coords.py --sido 서울      # 한 지역만
    python store_coords.py --radius 300    # 반경을 좁게

온누리 가맹점 CSV 에는 주소가 없지만, 소상공인시장진흥공단의 '상가(상권)정보'에는
전국 상가의 상호명과 좌표가 있다. 상호명이 같고 **소속 시장에서 반경 안에 있는** 곳을
그 가맹점으로 본다. 시장 좌표를 기준점으로 쓰기 때문에 market_address.py 를 먼저 돌려야 한다.

이름만으로 맞추면 흔한 상호가 엉뚱한 곳에 걸린다. 반경 제약이 그걸 막는다.
같은 반경 안에 동명 가게가 둘 이상이면 어느 쪽인지 알 수 없으므로 **찍지 않고 건너뛴다.**
(서울 기준 1.7%. 추측해서 틀린 좌표를 넣느니 비워두는 편이 낫다.)

파일이 336MB 라 data/ 에 한 번 받아두고 다시 쓴다. 압축은 풀지 않고 그대로 읽는다.
"""

import argparse
import collections
import csv
import io
import math
import os
import sys
import zipfile

import requests

import fetch_data
import onnuri_db

DATASET_URL = "https://www.data.go.kr/data/15083033/fileData.do"
ZIP_NAME = "상가상권정보.zip"

# 압축 안의 파일은 시/도별로 나뉘어 있다. 전남과 광주는 한 파일에 같이 들어있다.
REGION_FILE = {"전남": "전남광주", "광주": "전남광주"}


def zip_path():
    return os.path.join(onnuri_db.BASE_DIR, "data", ZIP_NAME)


def ensure_zip():
    """없으면 내려받는다. 336MB 라 한 번 받으면 다시 쓴다."""
    path = zip_path()
    if os.path.exists(path) and os.path.getsize(path) > 100 * 1024 * 1024:
        print(f"이미 있음: {path}  ({os.path.getsize(path) / 1024 / 1024:.0f} MB)")
        return path

    session = requests.Session()
    session.headers.update({"User-Agent": fetch_data.UA})
    print("상가(상권)정보 내려받는 중… 336MB 라 몇 분 걸립니다.")
    _, content = fetch_data.download(session, DATASET_URL, ZIP_NAME)

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)
    print(f"저장 완료: {path}  ({len(content) / 1024 / 1024:.0f} MB)")
    return path


def member_for(archive, sido):
    """시/도에 해당하는 압축 안 파일 이름."""
    want = REGION_FILE.get(sido, sido)
    for info in archive.infolist():
        try:
            name = info.filename.encode("cp437").decode("cp949")
        except (UnicodeEncodeError, UnicodeDecodeError):
            name = info.filename
        if name.endswith(".csv") and want in name:
            return info.filename
    return None


def norm(name):
    """비교용 상호명. 괄호 안 설명과 기호·공백을 없앤다."""
    import re
    return re.sub(r"[^0-9a-z가-힣]", "", re.sub(r"\(.*?\)", "", name or "").lower())


def meters(lat1, lng1, lat2, lng2):
    radius = 6371000.0
    rad = math.radians
    return 2 * radius * math.asin(math.sqrt(
        math.sin(rad(lat2 - lat1) / 2) ** 2
        + math.cos(rad(lat1)) * math.cos(rad(lat2)) * math.sin(rad(lng2 - lng1) / 2) ** 2))


CELL = 0.02  # 약 2km. 반경 검사를 이 격자 안에서만 한다.


def process_sido(conn, archive, sido, radius):
    """한 시/도를 처리하고 (찍음, 모호해서 건너뜀, 못찾음) 을 돌려준다."""
    markets = conn.execute(
        "SELECT id, lat, lng FROM markets WHERE lat IS NOT NULL AND sido = ?", (sido,)).fetchall()
    stores = conn.execute(
        "SELECT s.id, s.name, s.market_id FROM stores s JOIN markets m ON m.id = s.market_id "
        "WHERE m.lat IS NOT NULL AND m.sido = ?", (sido,)).fetchall()
    if not markets or not stores:
        return 0, 0, 0

    member = member_for(archive, sido)
    if member is None:
        print(f"  {sido}: 압축 안에 해당 파일이 없습니다.")
        return 0, 0, len(stores)

    grid = collections.defaultdict(list)
    for market in markets:
        grid[(int(market["lat"] / CELL), int(market["lng"] / CELL))].append(market)

    # 찾아야 할 (시장, 상호) 조합만 들고 있다가 그것만 걸러 담는다. 안 그러면 메모리가 터진다.
    wanted = collections.defaultdict(list)
    for store in stores:
        wanted[(store["market_id"], norm(store["name"]))].append(store["id"])

    found = collections.defaultdict(dict)
    with io.TextIOWrapper(archive.open(member), encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                lat, lng = float(row["위도"]), float(row["경도"])
            except (TypeError, ValueError):
                continue
            cell_y, cell_x = int(lat / CELL), int(lng / CELL)
            keys = {norm(row["상호명"]), norm((row["상호명"] or "") + (row["지점명"] or ""))}
            keys.discard("")
            if not keys:
                continue
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    for market in grid.get((cell_y + dy, cell_x + dx), ()):
                        distance = meters(lat, lng, market["lat"], market["lng"])
                        if distance > radius:
                            continue
                        for key in keys:
                            if (market["id"], key) in wanted:
                                found[(market["id"], key)][(round(lat, 6), round(lng, 6))] = (
                                    round(distance),
                                    row["상권업종대분류명"], row["상권업종소분류명"])

    placed = skipped = 0
    for key, spots in found.items():
        # 같은 이름이 반경 안에 여러 군데면 어느 쪽인지 알 수 없다. 건너뛴다.
        if len(spots) > 1:
            skipped += len(wanted[key])
            continue
        (lat, lng), (distance, major, name) = next(iter(spots.items()))
        for store_id in wanted[key]:
            conn.execute(
                "UPDATE stores SET lat=?, lng=?, coord_dist=?, cat_major=?, cat_name=? "
                "WHERE id=?", (lat, lng, distance, major, name, store_id))
            placed += 1
    conn.commit()

    missed = len(stores) - placed - skipped
    print(f"  {sido}: 가맹점 {len(stores):,}곳 → 찍음 {placed:,} · "
          f"모호해서 건너뜀 {skipped:,} · 못찾음 {missed:,}")
    return placed, skipped, missed


def report(conn):
    one = lambda sql: conn.execute(sql).fetchone()[0]
    stores = one("SELECT COUNT(*) FROM stores")
    located = one("SELECT COUNT(*) FROM stores WHERE lat IS NOT NULL")
    in_mapped = one("SELECT COUNT(*) FROM stores WHERE market_id IN "
                    "(SELECT id FROM markets WHERE lat IS NOT NULL)")
    print(f"가맹점 좌표: {located:,}/{stores:,}곳 "
          f"(좌표 있는 시장 소속 {in_mapped:,}곳 기준 {100 * located / max(in_mapped, 1):.1f}%)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sido", help="시/도 하나만 처리 (예: 서울)")
    parser.add_argument("--radius", type=float, default=500.0,
                        help="시장에서 이 거리 안에 있는 동명 가게만 인정 (기본 500m)")
    args = parser.parse_args()

    conn = onnuri_db.init()
    path = ensure_zip()

    sidos = [args.sido] if args.sido else [
        row[0] for row in conn.execute("SELECT DISTINCT sido FROM markets ORDER BY sido")]

    print(f"반경 {args.radius:.0f}m 안에서 상호명이 같은 곳을 찾습니다.")
    totals = [0, 0, 0]
    with zipfile.ZipFile(path) as archive:
        for sido in sidos:
            result = process_sido(conn, archive, sido, args.radius)
            totals = [a + b for a, b in zip(totals, result)]

    print(f"\n합계: 찍음 {totals[0]:,} · 모호 {totals[1]:,} · 못찾음 {totals[2]:,}")
    report(conn)


if __name__ == "__main__":
    sys.exit(main())
