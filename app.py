# -*- coding: utf-8 -*-
"""
온누리 가맹점 지도 - 로컬 서버.

    python app.py

실행하면 기본 브라우저가 열린다. 데이터는 onnuri.db(SQLite)에서 읽는다.
"""

import os
import threading
import webbrowser

from flask import Flask, jsonify, request

import onnuri_db

app = Flask(__name__, static_folder="static", static_url_path="/static")
CONFIG = onnuri_db.load_config()

MAX_MARKERS = 1500


@app.route("/")
def index():
    path = os.path.join(onnuri_db.BASE_DIR, "static", "index.html")
    with open(path, encoding="utf-8") as f:
        html = f.read()
    return html.replace("__KAKAO_JS_KEY__", CONFIG["kakao_js_key"])


def build_filters(args):
    """검색어/가맹유형 필터를 WHERE 조각과 파라미터로."""
    clauses = []
    params = []
    keyword = (args.get("q") or "").strip()
    if keyword:
        clauses.append("(name LIKE ? OR market LIKE ? OR items LIKE ?)")
        params += [f"%{keyword}%"] * 3
    if args.get("paper") == "1":
        clauses.append("paper = 1")
    if args.get("digital") == "1":
        clauses.append("digital = 1")
    return clauses, params


def rows_to_json(rows):
    return [
        {
            "id": r["id"], "name": r["name"], "market": r["market"],
            "address": r["address"], "items": r["items"],
            "paper": r["paper"], "digital": r["digital"],
            "sigungu": r["sigungu"], "lat": r["lat"], "lng": r["lng"],
        }
        for r in rows
    ]


@app.route("/api/stores")
def api_stores():
    """지도 화면(bbox) 안의 가맹점."""
    try:
        bounds = [float(request.args[k]) for k in ("swLat", "swLng", "neLat", "neLng")]
    except (KeyError, ValueError):
        return jsonify({"error": "bbox 파라미터가 필요합니다."}), 400

    clauses, params = build_filters(request.args)
    where = " AND ".join(
        ["lat BETWEEN ? AND ?", "lng BETWEEN ? AND ?"] + clauses)
    sql_params = [bounds[0], bounds[2], bounds[1], bounds[3]] + params

    conn = onnuri_db.connect()
    total = conn.execute(
        f"SELECT COUNT(*) FROM stores WHERE {where}", sql_params).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM stores WHERE {where} LIMIT ?", sql_params + [MAX_MARKERS])
    stores = rows_to_json(rows)
    conn.close()

    return jsonify({"total": total, "truncated": total > len(stores), "stores": stores})


@app.route("/api/search")
def api_search():
    """이름으로 찾아서 지도를 옮길 때 쓰는 전국 검색."""
    keyword = (request.args.get("q") or "").strip()
    if not keyword:
        return jsonify({"stores": []})

    conn = onnuri_db.connect()
    rows = conn.execute(
        """SELECT * FROM stores
           WHERE lat IS NOT NULL AND (name LIKE ? OR market LIKE ?)
           LIMIT 50""",
        (f"%{keyword}%", f"%{keyword}%"))
    stores = rows_to_json(rows)
    conn.close()
    return jsonify({"stores": stores})


@app.route("/api/stats")
def api_stats():
    conn = onnuri_db.connect()
    total = conn.execute("SELECT COUNT(*) FROM stores").fetchone()[0]
    mapped = conn.execute(
        "SELECT COUNT(*) FROM stores WHERE lat IS NOT NULL").fetchone()[0]
    conn.close()
    return jsonify({"total": total, "mapped": mapped})


if __name__ == "__main__":
    onnuri_db.init()
    port = CONFIG.get("port", 5173)
    url = f"http://127.0.0.1:{port}/"
    print(f"온누리 가맹점 지도: {url}  (종료: Ctrl+C)")
    if not os.environ.get("WERKZEUG_RUN_MAIN"):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False)
