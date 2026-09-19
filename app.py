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

from flask import Flask, jsonify, make_response, request

import onnuri_db

app = Flask(__name__, static_folder="static", static_url_path="/static")
CONFIG = onnuri_db.load_config()

MAX_MARKETS = 500
MAX_STORES = 2000

# 상권정보 소분류 42종은 드롭다운에 쓰기엔 많고 결이 섞여 있다("떡/한과"와 "횟집"이
# 같은 층위에 있다). 뭘 먹을지 고르는 기준으로 묶는다. 순서가 드롭다운 순서다.
# cat_name 은 대분류 하나에만 속하므로 이름만 걸면 음식 조건이 따로 필요 없다.
FOOD_GROUPS = {
    "한식": ["백반/한정식", "국/탕/찌개류", "국수/칼국수", "냉면/밀면",
             "전/부침개", "기타 한식 음식점", "구내식당"],
    "분식·간식": ["김밥/만두/분식", "떡/한과", "그 외 기타 간이 음식점",
                  "토스트/샌드위치/샐러드"],
    "고기·구이": ["돼지고기 구이/찜", "소고기 구이/찜", "닭/오리고기 구이/찜",
                  "곱창 전골/구이", "족발/보쌈"],
    "카페·디저트": ["카페", "빵/도넛", "아이스크림/빙수"],
    "회·해산물": ["횟집", "일식 회/초밥", "해산물 구이/찜", "복 요리 전문"],
    "치킨·피자·버거": ["치킨", "피자", "버거"],
    "주점": ["요리 주점", "생맥주 전문", "일반 유흥 주점"],
    "중식": ["중국집", "마라탕/훠궈"],
    "양식": ["경양식", "파스타/스테이크", "패밀리레스토랑", "기타 서양식 음식점"],
    "일식": ["일식 카레/돈가스/덮밥", "일식 면 요리", "기타 일식 음식점"],
    "아시안": ["베트남식 전문", "기타 동남아식 전문", "분류 안된 외국식 음식점"],
}
# 위 어디에도 없는 음식 소분류(나중에 상권정보가 새 분류를 내면)는 여기로 떨어진다.
ETC_GROUP = "기타"


def static_version():
    """static/ 안에서 가장 최근에 바뀐 시각. 주소 뒤에 붙여 캐시를 깬다."""
    folder = os.path.join(onnuri_db.BASE_DIR, "static")
    return int(max(os.path.getmtime(os.path.join(folder, name))
                   for name in os.listdir(folder)))


@app.route("/")
def index():
    path = os.path.join(onnuri_db.BASE_DIR, "static", "index.html")
    with open(path, encoding="utf-8") as f:
        html = f.read()
    html = html.replace("__KAKAO_JS_KEY__", CONFIG["kakao_js_key"])
    # app.js 를 고쳤는데 index.html 은 예전 것이 캐시돼 있으면 화면이 엇갈린다.
    html = html.replace("__V__", str(static_version()))
    # 묶음 목록을 HTML 에 또 적으면 둘이 어긋난다. 서버가 한 곳에서 만들어 준다.
    options = "".join(f'<option value="{g}">{g}</option>'
                      for g in list(FOOD_GROUPS) + [ETC_GROUP])
    html = html.replace("__CAT_OPTIONS__",
                        '<option value="">식당 종류 전체</option>' + options)
    response = make_response(html)
    response.headers["Cache-Control"] = "no-store"
    return response


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
    if args.get("digital") == "1":
        clauses.append("s.digital = 1")
    # 업종은 상권정보로 확인된 가맹점에만 있다. 켜면 그 가맹점만 남는다.
    if args.get("food") == "1":
        clauses.append("s.cat_major = '음식'")
    group = args.get("cat")
    if group in FOOD_GROUPS:
        names = FOOD_GROUPS[group]
        clauses.append("s.cat_name IN (%s)" % ",".join("?" * len(names)))
        params += names
    elif group == ETC_GROUP:
        mapped = [n for names in FOOD_GROUPS.values() for n in names]
        clauses.append("s.cat_major = '음식' AND s.cat_name NOT IN (%s)"
                       % ",".join("?" * len(mapped)))
        params += mapped
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
        f"""SELECT s.id, s.name, s.items, s.paper, s.digital, s.reg_year,
                   s.lat, s.lng, s.cat_major, s.cat_name
            FROM markets m JOIN stores s ON s.market_id = m.id
            WHERE {where}
            ORDER BY s.name""",
        [market_id] + params)
    stores = [dict(r) for r in rows]
    conn.close()

    return jsonify({"market": dict(market), "stores": stores})


@app.route("/api/stores")
def api_stores():
    """지도 화면 안의 가맹점 좌표. 줌인했을 때 개별 핀으로 쓴다.

    한 건물에 수백 곳이 들어있는 시장이 있다(부산진시장 548곳). 상권정보가 건물 좌표를
    공통으로 주기 때문인데, 그대로 찍으면 마커가 한 점에 겹친다. 같은 좌표는 묶어서 돌려준다.
    """
    try:
        sw_lat, sw_lng, ne_lat, ne_lng = (
            float(request.args[k]) for k in ("swLat", "swLng", "neLat", "neLng"))
    except (KeyError, ValueError):
        return jsonify({"error": "bbox 파라미터가 필요합니다."}), 400

    clauses, params = store_filters(request.args)
    where = " AND ".join(
        ["s.lat BETWEEN ? AND ?", "s.lng BETWEEN ? AND ?"] + clauses)
    sql_params = [sw_lat, ne_lat, sw_lng, ne_lng] + params

    conn = onnuri_db.connect()
    rows = conn.execute(
        f"""SELECT s.id, s.name, s.items, s.paper, s.digital, s.lat, s.lng,
                   s.cat_major, s.cat_name, m.name AS market, m.sido, m.sigungu
            FROM markets m JOIN stores s ON s.market_id = m.id
            WHERE {where}
            ORDER BY s.lat, s.lng
            LIMIT ?""",
        sql_params + [MAX_STORES + 1])
    stores = list(rows)
    conn.close()

    truncated = len(stores) > MAX_STORES
    points = {}
    for row in stores[:MAX_STORES]:
        point = points.setdefault((row["lat"], row["lng"]), {
            "lat": row["lat"], "lng": row["lng"],
            "market": row["market"], "sido": row["sido"], "sigungu": row["sigungu"],
            "stores": [],
        })
        point["stores"].append(
            {k: row[k] for k in
             ("id", "name", "items", "paper", "digital", "cat_major", "cat_name")})

    return jsonify({"truncated": truncated, "points": list(points.values())})


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
