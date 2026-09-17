# -*- coding: utf-8 -*-
"""SQLite 스키마와 공용 접속 함수."""

import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "onnuri.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS stores (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT NOT NULL,
    market   TEXT,
    address  TEXT NOT NULL,
    items    TEXT,
    paper    INTEGER DEFAULT 0,
    digital  INTEGER DEFAULT 0,
    reg_year TEXT,
    sido     TEXT,
    sigungu  TEXT,
    lat      REAL,
    lng      REAL,
    UNIQUE(name, address)
);
CREATE INDEX IF NOT EXISTS idx_stores_pos  ON stores(lat, lng);
CREATE INDEX IF NOT EXISTS idx_stores_area ON stores(sido, sigungu);
CREATE INDEX IF NOT EXISTS idx_stores_name ON stores(name);

CREATE TABLE IF NOT EXISTS geocache (
    address TEXT PRIMARY KEY,
    lat     REAL,
    lng     REAL,
    status  TEXT NOT NULL
);
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
