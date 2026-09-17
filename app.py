# -*- coding: utf-8 -*-
"""
온누리 가맹점 지도 - 로컬 서버.

    python app.py

실행하면 기본 브라우저가 열린다. 데이터는 onnuri.db(SQLite)에서 읽는다.
지도에 찍히는 것은 시장·상점가이고, 가맹점은 그 안의 목록으로 보여준다.
"""

import os
import threading
import webbrowser

from flask import Flask, jsonify, request

import onnuri_db

app = Flask(__name__, static_folder="static", static_url_path="/static")
CONFIG = onnuri_db.load_config()

MAX_MARKETS = 500


@app.route("/")
def index():
    path = os.path.join(onnuri_db.BASE_DIR, "static", "index.html")
    with open(path, encoding="utf-8") as f:
        html = f.read()
    return html.replace("__KAKAO_JS_KEY__", CONFIG["kakao_js_key"])


def store_filters(args):
    """검색어·가맹유형 필터를 WHERE 조각과 파라미터로.

    검색어는 시장명에도 걸린다. 시장 이름이 맞으면 그 시장의 가맹점이 전부 나온다.
    """
    clauses = []
    params = []
    keyword = (args.get("q") or "").strip()
    if keyword:
        clauses.append("(m.name LIKE ? OR s.name LIKE ? OR s.items LIKE ?)")
        params += ["%" + keyword + "%"] * 3
    if args.get("paper") == "1":
        clauses.append("s.paper = 1")
    if args.get("digital") == "1":
        clauses.append("s.digital = 1")
    return clauses, params


@app.route("/api/markets")
def api_markets():
    """지도 화면(bbox) 안의 시장·상점가와 조건에 맞는 가맹점 수."""
    try:
        sw_lat, sw_lng, ne_lat, ne_lng = (
            float(request.args[k]) for k in ("swLat", "swLng", "neLat", "neLng"))
    except (KeyError, ValueError):
        return jsonify({"error": "bbox 파라미터가 필요합니다."}), 400

    clauses, params = store_filters(request.args)
    where = " AND ".join(
        ["m.lat BETWEEN ? AND ?", "m.lng BETWEEN ? AND ?"] + clauses)
    sql_params = [sw_lat, ne_lat, sw_lng, ne_lng] + params

    conn = onnuri_db.connect()
    rows = conn.execute(
        f"""SELECT m.id, m.name, m.sido, m.sigungu, m.address, m.lat, m.lng,
                   COUNT(s.id) AS stores
            FROM markets m JOIN stores s ON s.market_id = m.id
            WHERE {where}
            GROUP BY m.id
            ORDER BY stores DESC
            LIMIT ?""",
        sql_params + [MAX_MARKETS + 1])
    markets = [dict(r) for r in rows]
    conn.close()

    truncated = len(markets) > MAX_MARKETS
    return jsonify({"truncated": truncated, "markets": markets[:MAX_MARKETS]})


@app.route("/api/markets/<int:market_id>")
def api_market_detail(market_id):
    """시장 하나와 그 안의 가맹점 목록."""
    clauses, params = store_filters(request.args)
    where = " AND ".join(["m.id = ?"] + clauses)

    conn = onnuri_db.connect()
    market = conn.execute("SELECT * FROM markets WHERE id = ?", (market_id,)).fetchone()
    if market is None:
        conn.close()
        return jsonify({"error": "없는 시장입니다."}), 404

    rows = conn.execute(
        f"""SELECT s.id, s.name, s.items, s.paper, s.digital, s.reg_year
            FROM markets m JOIN stores s ON s.market_id = m.id
            WHERE {where}
            ORDER BY s.name""",
        [market_id] + params)
    stores = [dict(r) for r in rows]
    conn.close()

    return jsonify({"market": dict(market), "stores": stores})


@app.route("/api/search")
def api_search():
    """지도를 옮기기 위한 전국 검색. 시장명 또는 가맹점명으로 찾는다."""
    keyword = (request.args.get("q") or "").strip()
    if not keyword:
        return jsonify({"markets": []})

    like = "%" + keyword + "%"
    conn = onnuri_db.connect()
    rows = conn.execute(
        """SELECT m.id, m.name, m.sido, m.sigungu, m.lat, m.lng,
                  COUNT(s.id) AS stores
           FROM markets m JOIN stores s ON s.market_id = m.id
           WHERE m.lat IS NOT NULL AND (m.name LIKE ? OR s.name LIKE ?)
           GROUP BY m.id
           ORDER BY (m.name LIKE ?) DESC, stores DESC
           LIMIT 20""",
        (like, like, like))
    markets = [dict(r) for r in rows]
    conn.close()
    return jsonify({"markets": markets})


@app.route("/api/stats")
def api_stats():
    conn = onnuri_db.connect()
    one = lambda sql: conn.execute(sql).fetchone()[0]
    stats = {
        "markets": one("SELECT COUNT(*) FROM markets"),
        "mapped": one("SELECT COUNT(*) FROM markets WHERE lat IS NOT NULL"),
        "stores": one("SELECT COUNT(*) FROM stores"),
    }
    conn.close()
    return jsonify(stats)


if __name__ == "__main__":
    onnuri_db.init()
    port = CONFIG.get("port", 5173)
    url = f"http://127.0.0.1:{port}/"
    print(f"온누리 가맹점 지도: {url}  (종료: Ctrl+C)")
    if not os.environ.get("WERKZEUG_RUN_MAIN"):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False)
