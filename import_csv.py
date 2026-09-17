# -*- coding: utf-8 -*-
"""
공공데이터포털 '소상공인시장진흥공단_전국 온누리상품권 가맹점 현황' CSV 를 SQLite 에 적재한다.

사용법:
    python import_csv.py data/온누리상품권_가맹점.csv

공개 회차마다 컬럼명이 조금씩 달라서, 헤더에 포함된 키워드로 매칭한다.
가맹점은 소속 시장에 매달아 저장한다. 재실행하면 기존 항목은 정보만 갱신한다.
"""

import csv
import io
import sys

import onnuri_db

# 컬럼 후보: (내부 이름, 헤더에 포함되면 매칭되는 키워드들)
COLUMN_HINTS = [
    ("name",     ["가맹점명", "상호", "점포명", "업체명"]),
    ("market",   ["시장", "상점가"]),
    ("sido",     ["소재지", "주소"]),
    ("items",    ["취급품목", "품목", "업종"]),
    ("paper",    ["지류"]),
    ("digital",  ["디지털", "모바일", "카드"]),
    ("reg_year", ["등록년도", "등록연도", "가맹년도"]),
]

TRUE_TOKENS = {"y", "o", "1", "예", "가능", "사용", "true", "해당"}


def read_rows(path):
    """data.go.kr CSV 는 회차에 따라 UTF-8 이거나 CP949 다."""
    for encoding in ("utf-8-sig", "cp949"):
        try:
            with open(path, encoding=encoding, newline="") as f:
                text = f.read()
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SystemExit("인코딩을 판별하지 못했습니다: " + path)

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise SystemExit("CSV 헤더를 읽지 못했습니다.")
    return reader.fieldnames, list(reader)


def map_columns(fieldnames):
    """헤더 → 내부 컬럼 매핑. 매칭 안 되면 빠진다."""
    mapping = {}
    for key, hints in COLUMN_HINTS:
        for header in fieldnames:
            clean = (header or "").replace(" ", "")
            if any(h in clean for h in hints):
                mapping[key] = header
                break
    return mapping


def to_bool(value):
    return 1 if (value or "").strip().lower() in TRUE_TOKENS else 0


def main(path):
    fieldnames, rows = read_rows(path)
    mapping = map_columns(fieldnames)

    for required in ("name", "market", "sido"):
        if required not in mapping:
            raise SystemExit(
                "필수 컬럼(" + required + ")을 찾지 못했습니다.\n"
                "읽은 헤더: " + str(fieldnames)
            )

    print(f"헤더 매핑: {mapping}")
    print(f"CSV 행 수: {len(rows):,}")

    conn = onnuri_db.init()
    skipped = 0
    market_ids = {}

    for row in rows:
        def cell(key):
            header = mapping.get(key)
            return (row.get(header) or "").strip() if header else ""

        name = cell("name")
        market = cell("market")
        sido = cell("sido")          # 공공데이터의 '소재지'는 시/도 한 단어뿐이다
        if not name or not market or not sido:
            skipped += 1
            continue

        key = (market, sido)
        if key not in market_ids:
            conn.execute("INSERT OR IGNORE INTO markets (name, sido) VALUES (?, ?)", key)
            market_ids[key] = conn.execute(
                "SELECT id FROM markets WHERE name = ? AND sido = ?", key).fetchone()[0]

        conn.execute(
            """
            INSERT INTO stores (market_id, name, items, paper, digital, reg_year)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(market_id, name) DO UPDATE SET
                items    = excluded.items,
                paper    = excluded.paper,
                digital  = excluded.digital,
                reg_year = excluded.reg_year
            """,
            (market_ids[key], name, cell("items"),
             to_bool(cell("paper")), to_bool(cell("digital")), cell("reg_year")),
        )

    conn.commit()
    markets = conn.execute("SELECT COUNT(*) FROM markets").fetchone()[0]
    stores = conn.execute("SELECT COUNT(*) FROM stores").fetchone()[0]
    print(f"건너뜀: {skipped:,}건 (상호/시장명/소재지 누락)")
    print(f"DB: 시장·상점가 {markets:,}곳, 가맹점 {stores:,}곳")
    print("\n다음: python geocode_markets.py  (시장 좌표 확보)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("사용법: python import_csv.py <CSV경로>")
    main(sys.argv[1])
