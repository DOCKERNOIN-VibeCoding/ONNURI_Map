# -*- coding: utf-8 -*-
"""
공공데이터포털 '소상공인시장진흥공단_전국 온누리상품권 가맹점 현황' CSV 를 SQLite 에 적재한다.

사용법:
    python import_csv.py data/온누리상품권_가맹점.csv

공개 회차마다 컬럼명이 조금씩 달라서, 헤더에 포함된 키워드로 매칭한다.
이미 들어있는 가맹점(상호+주소 동일)은 정보만 갱신하고 좌표는 보존한다.
"""

import csv
import io
import sys

import onnuri_db

# 컬럼 후보: (내부 이름, 헤더에 포함되면 매칭되는 키워드들)
COLUMN_HINTS = [
    ("name",     ["가맹점명", "상호", "점포명", "업체명"]),
    ("market",   ["시장", "상점가"]),
    ("address",  ["소재지", "주소"]),
    ("items",    ["취급품목", "품목", "업종"]),
    ("paper",    ["지류"]),
    ("digital",  ["디지털", "모바일", "카드"]),
    ("reg_year", ["등록년도", "등록연도", "가맹년도"]),
]

TRUE_TOKENS = {"y", "o", "1", "예", "가능", "사용", "true", "해당"}


def read_rows(path):
    """data.go.kr CSV 는 CP949 인 경우가 많다. UTF-8 우선, 실패 시 CP949."""
    for encoding in ("utf-8-sig", "cp949"):
        try:
            with open(path, encoding=encoding, newline="") as f:
                text = f.read()
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SystemExit(f"인코딩을 판별하지 못했습니다: {path}")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise SystemExit("CSV 헤더를 읽지 못했습니다.")
    return reader.fieldnames, list(reader)


def map_columns(fieldnames):
    """헤더 → 내부 컬럼 매핑. 매칭 안 되면 None."""
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


def split_area(address):
    parts = (address or "").split()
    return (parts[0] if parts else ""), (parts[1] if len(parts) > 1 else "")


def main(path):
    fieldnames, rows = read_rows(path)
    mapping = map_columns(fieldnames)

    for required in ("name", "address"):
        if required not in mapping:
            raise SystemExit(
                f"필수 컬럼({required})을 찾지 못했습니다.\n읽은 헤더: {fieldnames}"
            )

    print(f"헤더 매핑: {mapping}")
    print(f"CSV 행 수: {len(rows):,}")

    conn = onnuri_db.init()
    inserted = 0
    skipped = 0

    for row in rows:
        def cell(key):
            header = mapping.get(key)
            return (row.get(header) or "").strip() if header else ""

        name = cell("name")
        address = cell("address")
        if not name or not address:
            skipped += 1
            continue

        sido, sigungu = split_area(address)
        conn.execute(
            """
            INSERT INTO stores (name, market, address, items, paper, digital,
                                reg_year, sido, sigungu)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name, market, address) DO UPDATE SET
                items    = excluded.items,
                paper    = excluded.paper,
                digital  = excluded.digital,
                reg_year = excluded.reg_year
            """,
            (name, cell("market"), address, cell("items"),
             to_bool(cell("paper")), to_bool(cell("digital")),
             cell("reg_year"), sido, sigungu),
        )
        inserted += 1

    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM stores").fetchone()[0]
    print(f"적재 완료: {inserted:,}건 처리, {skipped:,}건 건너뜀 (상호/주소 누락)")
    print(f"DB 총 가맹점: {total:,}건")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("사용법: python import_csv.py <CSV경로>")
    main(sys.argv[1])
