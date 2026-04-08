"""
機票比價系統 - Flight Compare
使用 Travelpayouts Data API 搜尋最便宜的機票（免費、無次數限制）
"""
import json
import os
import time
from datetime import datetime, timedelta

import airportsdata
import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# ─────────────── 全球機場資料庫（7800+ 個機場） ───────────────

_raw_airports = airportsdata.load("IATA")
AIRPORTS_DB = {}
for iata_code, info in _raw_airports.items():
    AIRPORTS_DB[iata_code] = {
        "code": iata_code,
        "name": info.get("name", ""),
        "city": info.get("city", ""),
        "country": info.get("country", ""),
    }

# IATA 城市代碼對照（主要城市有多個機場時使用城市代碼）
CITY_CODES = {
    "NRT": "TYO", "HND": "TYO",  # 東京
    "KIX": "OSA", "ITM": "OSA",  # 大阪
    "JFK": "NYC", "LGA": "NYC", "EWR": "NYC",  # 紐約
    "LAX": "LAX",
    "CDG": "PAR", "ORY": "PAR",  # 巴黎
    "LHR": "LON", "LGW": "LON", "STN": "LON",  # 倫敦
    "ICN": "SEL", "GMP": "SEL",  # 首爾
    "TPE": "TPE",
    "BKK": "BKK",
    "SIN": "SIN",
    "SGN": "SGN",
}


def load_config():
    """讀取設定：優先用環境變數（雲端部署用），否則讀 config.json（本機用）"""
    env_key = os.environ.get("TRAVELPAYOUTS_TOKEN", "")
    if env_key:
        return {"api_token": env_key}
    # 也支援舊的 SERPAPI_KEY 環境變數名（過渡期）
    env_key2 = os.environ.get("SERPAPI_KEY", "")
    if env_key2:
        return {"api_token": env_key2}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # 支援舊格式
            token = data.get("api_token", "") or data.get("serpapi_key", "")
            return {"api_token": token}
    return {"api_token": ""}


# ─────────────── 航空公司資料 ───────────────

# 台灣航空公司代碼對照
TW_AIRLINE_CODES = {
    "CI": "中華航空", "BR": "長榮航空", "JX": "星宇航空",
    "IT": "台灣虎航", "B7": "立榮航空", "AE": "華信航空",
}
TW_AIRLINE_URLS = {
    "CI": "https://www.china-airlines.com/tw/zh/booking/book-flights/flight-search",
    "BR": "https://www.evaair.com/zh-tw/booking/flight-search/",
    "JX": "https://www.starlux-airlines.com/zh-TW/booking/flight-search",
    "IT": "https://www.tigerairtw.com/zh-tw/booking",
    "B7": "https://www.uniair.com.tw/",
    "AE": "https://www.mandarin-airlines.com/",
}

# 常見航空公司名稱
AIRLINE_NAMES = {
    "CI": "中華航空", "BR": "長榮航空", "JX": "星宇航空",
    "IT": "台灣虎航", "B7": "立榮航空", "AE": "華信航空",
    "CX": "國泰航空", "HX": "香港航空", "KA": "國泰港龍",
    "NH": "全日空 ANA", "JL": "日本航空 JAL", "MM": "樂桃航空",
    "7C": "濟州航空", "TW": "德威航空", "KE": "大韓航空",
    "OZ": "韓亞航空", "LJ": "真航空", "ZE": "易斯達航空",
    "SQ": "新加坡航空", "TR": "酷航 Scoot", "3K": "捷星亞洲",
    "TG": "泰國航空", "FD": "泰亞洲航空", "VJ": "越捷航空",
    "VN": "越南航空", "QH": "越竹航空",
    "MH": "馬來西亞航空", "AK": "亞洲航空",
    "PR": "菲律賓航空", "5J": "宿霧太平洋",
    "CZ": "中國南方航空", "MU": "中國東方航空", "CA": "中國國際航空",
    "HU": "海南航空", "ZH": "深圳航空",
    "AA": "美國航空", "UA": "聯合航空", "DL": "達美航空",
    "AF": "法國航空", "BA": "英國航空", "LH": "漢莎航空",
    "EK": "阿聯酋航空", "QR": "卡達航空", "TK": "土耳其航空",
}


# ─────────────── Travelpayouts Data API ───────────────

API_BASE = "https://api.travelpayouts.com"


def get_api_token():
    cfg = load_config()
    return cfg.get("api_token", "")


def search_cheap_tickets(origin, destination, depart_date=None, return_date=None,
                         direct=False, currency="TWD"):
    """使用 Travelpayouts 搜尋最便宜的機票"""
    token = get_api_token()
    if not token:
        return {"error": "未設定 API Token"}

    params = {
        "origin": origin,
        "destination": destination,
        "currency": currency,
        "token": token,
    }

    if depart_date:
        # API 接受 YYYY-MM 或 YYYY-MM-DD
        params["depart_date"] = depart_date
    if return_date:
        params["return_date"] = return_date
    if direct:
        params["direct"] = "true"

    resp = requests.get(
        f"{API_BASE}/v1/prices/cheap",
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def search_latest_prices(origin, destination, direct=False, one_way=False,
                         currency="TWD", limit=30):
    """取得最新已知票價"""
    token = get_api_token()
    if not token:
        return {"error": "未設定 API Token"}

    params = {
        "origin": origin,
        "destination": destination,
        "currency": currency,
        "limit": limit,
        "show_to_affiliates": "true",
        "sorting": "price",
        "token": token,
    }

    if direct:
        params["direct"] = "true"
    if one_way:
        params["one_way"] = "true"

    resp = requests.get(
        f"{API_BASE}/v2/prices/latest",
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def search_calendar_prices(origin, destination, depart_date, return_date=None,
                           currency="TWD"):
    """取得日曆價格（每天的最低價）"""
    token = get_api_token()
    if not token:
        return {"error": "未設定 API Token"}

    params = {
        "origin": origin,
        "destination": destination,
        "depart_date": depart_date,
        "currency": currency,
        "token": token,
    }
    if return_date:
        params["return_date"] = return_date

    resp = requests.get(
        f"{API_BASE}/v1/prices/calendar",
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def search_month_matrix(origin, destination, month, currency="TWD"):
    """取得月份價格矩陣"""
    token = get_api_token()
    if not token:
        return {"error": "未設定 API Token"}

    params = {
        "origin": origin,
        "destination": destination,
        "month": month,
        "currency": currency,
        "show_to_affiliates": "true",
        "token": token,
    }

    resp = requests.get(
        f"{API_BASE}/v2/prices/month-matrix",
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def get_city_code(iata):
    """取得城市代碼（Travelpayouts 部分 API 用城市代碼）"""
    return CITY_CODES.get(iata, iata)


def build_booking_urls(origin, destination, depart_date, return_date=None, adults=1):
    """建立各平台訂票連結"""
    dep = origin.upper()
    arr = destination.upper()

    google_flights_url = (
        f"https://www.google.com/travel/flights?q=Flights+to+{arr}+from+{dep}+on+{depart_date}"
    )
    trip_com_url = (
        f"https://www.trip.com/flights/{dep.lower()}-to-{arr.lower()}/tickets-{dep.lower()}-{arr.lower()}"
        f"?dcity={dep}&acity={arr}&ddate={depart_date}"
        f"&Allianceid=8060886&SID=304954294"
    )
    # Agoda 用 flights.agoda.com + 路徑參數格式
    if return_date:
        agoda_url = f"https://flights.agoda.com/flights/{dep}-{arr}/{depart_date}/{return_date}/{adults}adults"
    else:
        agoda_url = f"https://flights.agoda.com/flights/{dep}-{arr}/{depart_date}/{adults}adults"

    return google_flights_url, trip_com_url, agoda_url


def format_flight_result(ticket, origin, destination, adults=1):
    """將 Travelpayouts 的票價資料整理為前端格式"""
    dep = origin.upper()
    arr = destination.upper()

    # 解析日期
    depart_at = ticket.get("departure_at", "") or ticket.get("depart_date", "")
    return_at = ticket.get("return_at", "") or ticket.get("return_date", "")

    depart_date = depart_at[:10] if depart_at else ""
    return_date = return_at[:10] if return_at else ""

    # 出發/到達時間
    depart_time = depart_at[11:16] if len(depart_at) > 11 else ""
    return_time = return_at[11:16] if len(return_at) > 11 else ""

    # 價格
    price = ticket.get("value", 0) or ticket.get("price", 0)

    # 航空公司
    airline_code = ticket.get("airline", "")
    airline_name = AIRLINE_NAMES.get(airline_code, airline_code)

    # 轉機次數
    transfers = ticket.get("number_of_changes", 0) or ticket.get("transfers", 0)

    # 航班時長（分鐘）
    duration = ticket.get("duration", 0) or ticket.get("duration_to", 0)

    # 訂票連結
    google_url, trip_url, agoda_url = build_booking_urls(
        dep, arr, depart_date, return_date, adults
    )

    # 台灣航空公司官網連結
    airline_links = []
    if airline_code in TW_AIRLINE_CODES:
        airline_links.append({
            "carrier_code": airline_code,
            "name": TW_AIRLINE_CODES[airline_code],
            "url": TW_AIRLINE_URLS[airline_code],
        })

    # 建立航段資訊
    segments = [{
        "carrier_code": airline_code,
        "carrier_name": airline_name,
        "flight_number": f"{airline_code}",
        "departure_airport": dep,
        "departure_time": depart_time,
        "arrival_airport": arr,
        "arrival_time": "",
        "duration": format_minutes(duration) if duration else "",
    }]

    itinerary = {
        "duration": format_minutes(duration) if duration else "",
        "stops": transfers,
        "segments": segments,
    }

    return {
        "price": price,
        "currency": "TWD",
        "itineraries": [itinerary],
        "booking_url": google_url,
        "trip_com_url": trip_url,
        "agoda_url": agoda_url,
        "airline_links": airline_links,
        "seats_remaining": None,
        "is_best": False,
        "baggage_info": [],
        "baggage": {
            "carry_on": "依航空公司規定",
            "checked_bag": None,
            "checked_bag_fee": None,
        },
        "depart_date": depart_date,
        "return_date": return_date,
    }


def format_minutes(minutes):
    """將分鐘數轉為易讀格式"""
    if not minutes:
        return ""
    h = int(minutes) // 60
    m = int(minutes) % 60
    return f"{h}h {m:02d}m"


# ─────────────── Flask Routes ───────────────


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/search", methods=["POST"])
def api_search():
    """搜尋航班 API"""
    data = request.json
    origin = data.get("origin", "").strip().upper()
    destination = data.get("destination", "").strip().upper()
    depart_date = data.get("depart_date", "")
    return_date = data.get("return_date", "") or None
    adults = int(data.get("adults", 1))
    nonstop = data.get("nonstop", False)

    if not origin or not destination or not depart_date:
        return jsonify({"error": "請填寫出發地、目的地和出發日期"}), 400

    try:
        # 方法 1：用 latest prices 取得最新票價
        raw = search_latest_prices(
            origin, destination,
            direct=nonstop,
            one_way=(return_date is None),
            limit=30,
        )

        if "error" in raw:
            return jsonify({"error": f"API 錯誤：{raw['error']}"}), 500

        tickets = raw.get("data", [])

        # 方法 2：如果 latest 沒結果，嘗試 cheap tickets
        if not tickets:
            raw2 = search_cheap_tickets(
                origin, destination,
                depart_date=depart_date[:7],  # YYYY-MM
                return_date=return_date[:7] if return_date else None,
                direct=nonstop,
            )
            if "data" in raw2 and destination in raw2["data"]:
                dest_data = raw2["data"][destination]
                for key, ticket in dest_data.items():
                    tickets.append(ticket)

        # 整理結果
        results = []
        for ticket in tickets:
            result = format_flight_result(ticket, origin, destination, adults)
            if result["price"] > 0:
                results.append(result)

        # 標記最便宜的為 best
        results.sort(key=lambda x: x["price"])
        if results:
            results[0]["is_best"] = True

        return jsonify({"results": results, "count": len(results)})

    except requests.exceptions.HTTPError as e:
        error_detail = str(e)
        try:
            error_detail = e.response.json().get("error", str(e))
        except Exception:
            pass
        return jsonify({"error": f"API 錯誤：{error_detail}"}), 500
    except Exception as e:
        return jsonify({"error": f"搜尋失敗：{str(e)}"}), 500


@app.route("/api/smart_search", methods=["POST"])
def api_smart_search():
    """
    智慧搜尋：只要給預算 + 來回地點，自動掃未來日期找最便宜的來回機票。
    使用 Travelpayouts calendar API + month matrix 找最划算的日期。
    """
    data = request.json
    origin = data.get("origin", "").strip().upper()
    destination = data.get("destination", "").strip().upper()
    budget = int(data.get("budget", 999999))
    adults = int(data.get("adults", 1))
    nonstop = data.get("nonstop", False)
    trip_days_options = [int(d) for d in data.get("trip_days", [3, 5, 7])]
    search_months = int(data.get("search_months", 2))

    if not origin or not destination:
        return jsonify({"error": "請填寫出發地和目的地"}), 400
    if budget <= 0:
        return jsonify({"error": "請輸入有效的預算金額"}), 400

    all_results = []
    errors = []
    searched_combos = []

    try:
        # 方法 1：用 month-matrix 取得多個月份的價格
        today = datetime.now()
        for i in range(search_months):
            month_date = today + timedelta(days=30 * i)
            month_str = month_date.strftime("%Y-%m-01")

            try:
                raw = search_month_matrix(origin, destination, month_str)

                if "error" in raw:
                    errors.append(f"{month_str}: {raw['error']}")
                    continue

                tickets = raw.get("data", [])
                for ticket in tickets:
                    result = format_flight_result(ticket, origin, destination, adults)
                    if result["price"] > 0:
                        # 計算旅程天數
                        if result.get("depart_date") and result.get("return_date"):
                            try:
                                dep_dt = datetime.strptime(result["depart_date"], "%Y-%m-%d")
                                ret_dt = datetime.strptime(result["return_date"], "%Y-%m-%d")
                                trip_days = (ret_dt - dep_dt).days
                                result["trip_days"] = trip_days
                                result["combo_label"] = f"{result['depart_date']} 出發 → {result['return_date']} 回來（{trip_days}天）"

                                # 只保留符合旅行天數的
                                if trip_days_options and trip_days not in trip_days_options:
                                    # 允許 ±1 天的彈性
                                    if not any(abs(trip_days - opt) <= 1 for opt in trip_days_options):
                                        continue
                            except Exception:
                                result["trip_days"] = 0
                                result["combo_label"] = f"{result.get('depart_date', '?')} 出發"

                        all_results.append(result)
                        searched_combos.append(result.get("combo_label", ""))

                time.sleep(0.2)

            except Exception as e:
                errors.append(f"{month_str}: {str(e)}")
                continue

        # 方法 2：如果 month-matrix 沒結果，用 latest prices
        if not all_results:
            raw = search_latest_prices(origin, destination, direct=nonstop, limit=30)
            tickets = raw.get("data", [])
            for ticket in tickets:
                result = format_flight_result(ticket, origin, destination, adults)
                if result["price"] > 0:
                    result["trip_days"] = 0
                    result["combo_label"] = f"{result.get('depart_date', '?')} 出發"
                    all_results.append(result)

    except Exception as e:
        errors.append(str(e))

    # 篩選預算內
    filtered = [r for r in all_results if r["price"] <= budget]
    filtered.sort(key=lambda x: x["price"])

    # 如果預算內沒有，回傳全部最便宜的
    show_all = False
    if not filtered and all_results:
        all_results.sort(key=lambda x: x["price"])
        filtered = all_results[:10]
        show_all = True

    summary = {
        "total_found": len(all_results),
        "in_budget": len([r for r in all_results if r["price"] <= budget]),
        "combos_searched": len(searched_combos),
        "budget": budget,
        "cheapest_price": all_results[0]["price"] if all_results else None,
        "cheapest_combo": all_results[0].get("combo_label") if all_results else None,
        "over_budget": show_all,
    }

    return jsonify({
        "results": filtered[:30],
        "summary": summary,
        "errors": errors,
    })


@app.route("/api/explore", methods=["POST"])
def api_explore():
    """
    預算探索：給預算 + 出發地，自動掃描熱門目的地，
    看這個預算能去哪裡。
    """
    data = request.json
    origin = data.get("origin", "").strip().upper()
    budget = int(data.get("budget", 999999))
    adults = int(data.get("adults", 1))

    if not origin:
        return jsonify({"error": "請填寫出發地"}), 400
    if budget <= 0:
        return jsonify({"error": "請輸入有效的預算金額"}), 400

    # 10 個精選目的地（6 亞洲 / 2 美洲 / 2 歐洲）
    POPULAR_DESTINATIONS = {
        "NRT": {"name": "東京", "region": "日本"},
        "KIX": {"name": "大阪", "region": "日本"},
        "ICN": {"name": "首爾", "region": "韓國"},
        "BKK": {"name": "曼谷", "region": "泰國"},
        "SGN": {"name": "胡志明市", "region": "越南"},
        "SIN": {"name": "新加坡", "region": "新加坡"},
        "LAX": {"name": "洛杉磯", "region": "美國"},
        "JFK": {"name": "紐約", "region": "美國"},
        "CDG": {"name": "巴黎", "region": "法國"},
        "LHR": {"name": "倫敦", "region": "英國"},
    }

    destinations = {k: v for k, v in POPULAR_DESTINATIONS.items() if k != origin}

    results = []
    errors = []

    for dest_code, dest_info in destinations.items():
        try:
            raw = search_latest_prices(origin, dest_code, limit=5)
            tickets = raw.get("data", [])

            if tickets:
                # 找最便宜的
                cheapest_ticket = min(tickets, key=lambda t: t.get("value", 999999))
                cheapest_price = cheapest_ticket.get("value", 0)
                airline_code = cheapest_ticket.get("airline", "")
                transfers = cheapest_ticket.get("number_of_changes", 0)
                duration = cheapest_ticket.get("duration", 0) or cheapest_ticket.get("duration_to", 0)
                depart_date = (cheapest_ticket.get("departure_at", "") or "")[:10]

                google_url, trip_url, agoda_url = build_booking_urls(
                    origin, dest_code, depart_date
                )

                results.append({
                    "destination_code": dest_code,
                    "destination_name": dest_info["name"],
                    "region": dest_info["region"],
                    "cheapest_price": cheapest_price,
                    "cheapest_date": depart_date,
                    "carrier": AIRLINE_NAMES.get(airline_code, airline_code),
                    "duration": format_minutes(duration) if duration else "",
                    "stops": transfers,
                    "in_budget": cheapest_price <= budget,
                    "google_url": google_url,
                    "trip_url": trip_url,
                    "agoda_url": agoda_url,
                })

            time.sleep(0.2)

        except Exception as e:
            errors.append(f"{dest_code}: {str(e)}")
            continue

    results.sort(key=lambda x: x["cheapest_price"])
    in_budget = [r for r in results if r["in_budget"]]

    return jsonify({
        "results": results,
        "summary": {
            "total_searched": len(destinations),
            "total_found": len(results),
            "in_budget": len(in_budget),
            "budget": budget,
        },
        "errors": errors,
    })


@app.route("/api/airports", methods=["GET"])
def api_airports():
    """搜尋機場代碼（全球 7800+ 機場）"""
    keyword = request.args.get("q", "").strip().upper()
    if len(keyword) < 1:
        return jsonify([])

    results = []
    if keyword in AIRPORTS_DB:
        results.append(AIRPORTS_DB[keyword])

    for code, a in AIRPORTS_DB.items():
        if len(results) >= 10:
            break
        if code == keyword:
            continue
        searchable = f"{a['code']} {a['name']} {a['city']} {a['country']}".upper()
        if keyword in searchable:
            results.append(a)
    return jsonify(results)


@app.route("/api/config", methods=["GET"])
def api_config_status():
    """檢查 API 設定狀態"""
    cfg = load_config()
    configured = bool(cfg.get("api_token"))
    return jsonify({"configured": configured})


@app.route("/api/config", methods=["POST"])
def api_config_save():
    """儲存 API 設定（僅本機模式可用）"""
    if os.environ.get("TRAVELPAYOUTS_TOKEN") or os.environ.get("SERPAPI_KEY"):
        return jsonify({"ok": True, "msg": "雲端模式，API Token 已透過環境變數設定"})
    data = request.json
    cfg = load_config()
    cfg["api_token"] = data.get("api_key", "").strip()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return jsonify({"ok": True})


if __name__ == "__main__":
    print("=" * 50)
    print("  機票比價系統 啟動中...")
    print("  請在瀏覽器開啟 http://localhost:5000")
    print("=" * 50)
    app.run(debug=True, port=5000)
