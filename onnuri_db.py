# -*- coding: utf-8 -*-
"""SQLite 스키마와 공용 접속 함수.

공공데이터의 소재지가 시/도 단위뿐이라 가맹점별 좌표는 얻을 수 없다.
그래서 좌표는 '시장·상점가'가 갖고, 가맹점은 소속 시장에 매달린다.
"""

import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "onnuri.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS markets (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL,
    sido    TEXT NOT NULL,
    lat     REAL,
    lng     REAL,
    sigungu TEXT,          -- 지오코딩으로 알아낸 시군구 (네이버 검색어에 사용)
    address TEXT,          -- 지오코딩으로 알아낸 도로명 주소
    status  TEXT,          -- ok | fail | NULL(미시도)
    UNIQUE(name, sido)
);
CREATE INDEX IF NOT EXISTS idx_markets_pos ON markets(lat, lng);

CREATE TABLE IF NOT EXISTS stores (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id INTEGER NOT NULL REFERENCES markets(id),
    name      TEXT NOT NULL,
    items     TEXT,
    paper     INTEGER DEFAULT 0,
    digital   INTEGER DEFAULT 0,
    reg_year  TEXT,
    UNIQUE(market_id, name)
);
CREATE INDEX IF NOT EXISTS idx_stores_market ON stores(market_id);
CREATE INDEX IF NOT EXISTS idx_stores_name   ON stores(name);
"""


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init():
    conn = connect()
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def load_config():
    path = os.path.join(BASE_DIR, "config.json")
    if not os.path.exists(path):
        raise SystemExit(
            "config.json 이 없습니다. config.sample.json 을 복사해 config.json 으로 만들고 키를 넣으세요."
        )
    import json
    with open(path, encoding="utf-8") as f:
        return json.load(f)
