"""
機票比價系統 - Flight Compare
使用 SerpApi (Google Flights) 搜尋最便宜的機票
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


def load_config():
    """讀取設定：優先用環境變數（雲端部署用），否則讀 config.json（本機用）"""
    env_key = os.environ.get("SERPAPI_KEY", "")
    if env_key:
        return {"serpapi_key": env_key}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"serpapi_key": ""}


# ─────────────── SerpApi Google Flights ───────────────


def search_flights(origin, destination, depart_date, return_date=None,
                   adults=1, nonstop=False):
    """使用 SerpApi 搜尋 Google Flights"""
    cfg = load_config()
    api_key = cfg.get("serpapi_key", "")

    params = {
        "engine": "google_flights",
        "departure_id": origin.upper(),
        "arrival_id": destination.upper(),
        "outbound_date": depart_date,
        "adults": adults,
        "currency": "TWD",
        "hl": "zh-TW",
        "api_key": api_key,
    }

    if return_date:
        params["return_date"] = return_date
        params["type"] = "1"  # 來回
    else:
        params["type"] = "2"  # 單程

    if nonstop:
        params["stops"] = "0"

    resp = requests.get(
        "https://serpapi.com/search.json",
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def parse_serpapi_results(raw, origin, destination, depart_date):
    """將 SerpApi 回傳的 Google Flights 資料整理為前端格式"""
    results = []

    # 台灣航空公司代碼對照
    tw_airline_codes = {
        "CI": "中華航空", "BR": "長榮航空", "JX": "星宇航空",
        "IT": "台灣虎航", "B7": "立榮航空", "AE": "華信航空",
    }
    tw_airline_urls = {
        "CI": "https://www.china-airlines.com/tw/zh/booking/book-flights/flight-search",
        "BR": "https://www.evaair.com/zh-tw/booking/flight-search/",
        "JX": "https://www.starlux-airlines.com/zh-TW/booking/flight-search",
        "IT": "https://www.tigerairtw.com/zh-tw/booking",
        "B7": "https://www.uniair.com.tw/",
        "AE": "https://www.mandarin-airlines.com/",
    }

    dep = origin.upper()
    arr = destination.upper()

    # 通用訂票連結
    google_flights_url = (
        f"https://www.google.com/travel/flights?q=Flights+to+{arr}+from+{dep}+on+{depart_date}"
    )
    trip_com_url = (
        f"https://www.trip.com/flights/{dep.lower()}-to-{arr.lower()}/tickets-{dep.lower()}-{arr.lower()}"
        f"?dcity={dep}&acity={arr}&ddate={depart_date}"
        f"&Allianceid=8060886&SID=304954294"
    )
    agoda_url = (
        f"https://www.agoda.com/flights/results?origin={dep}&destination={arr}"
        f"&departDate={depart_date}&adults=1&locale=zh-tw&curr=TWD"
    )

    # 解析 best_flights（推薦航班）和 other_flights（其他航班）
    all_flights = []
    for flight in raw.get("best_flights", []):
        flight["_tag"] = "best"
        all_flights.append(flight)
    for flight in raw.get("other_flights", []):
        flight["_tag"] = "other"
        all_flights.append(flight)

    for flight in all_flights:
        price = flight.get("price")
        if price is None:
            continue

        legs = flight.get("flights", [])
        if not legs:
            continue

        # 收集航空公司 & 行李資訊
        all_carriers = set()
        segments = []
        baggage_info = []
        for leg in legs:
            carrier_code = leg.get("airline_code", "") or ""
            carrier_name = leg.get("airline", carrier_code)
            all_carriers.add(carrier_code)

            dep_airport = leg.get("departure_airport", {})
            arr_airport = leg.get("arrival_airport", {})

            # 行李資訊（從 extensions 取得）
            extensions = leg.get("extensions", [])
            for ext in extensions:
                if ext and ext not in baggage_info:
                    baggage_info.append(ext)

            segments.append({
                "carrier_code": carrier_code,
                "carrier_name": carrier_name,
                "flight_number": f"{carrier_code}{leg.get('flight_number', '')}",
                "departure_airport": dep_airport.get("id", ""),
                "departure_time": dep_airport.get("time", ""),
                "arrival_airport": arr_airport.get("id", ""),
                "arrival_time": arr_airport.get("time", ""),
                "duration": format_minutes(leg.get("duration", 0)),
            })

        # 從 flight 層級取行李資訊
        for ext in flight.get("extensions", []):
            if ext and ext not in baggage_info:
                baggage_info.append(ext)

        # 解析行李細節（carry_on_bag, checked_bag 等）
        baggage_details = parse_baggage(flight, legs)

        total_duration = flight.get("total_duration", 0)
        stops = len(legs) - 1

        itinerary = {
            "duration": format_minutes(total_duration),
            "stops": stops,
            "segments": segments,
        }

        # 台灣航空公司官網連結
        airline_links = []
        for code in all_carriers:
            if code in tw_airline_codes:
                airline_links.append({
                    "carrier_code": code,
                    "name": tw_airline_codes[code],
                    "url": tw_airline_urls[code],
                })

        results.append({
            "price": price,
            "currency": "TWD",
            "itineraries": [itinerary],
            "booking_url": google_flights_url,
            "trip_com_url": trip_com_url,
            "agoda_url": agoda_url,
            "airline_links": airline_links,
            "seats_remaining": None,
            "is_best": flight.get("_tag") == "best",
            "baggage_info": baggage_info,
            "baggage": baggage_details,
        })

    results.sort(key=lambda x: x["price"])
    return results


def parse_baggage(flight, legs):
    """解析行李資訊，整理成前端易用的格式"""
    baggage = {
        "carry_on": None,      # 手提行李
        "checked_bag": None,   # 託運行李
        "checked_bag_fee": None,  # 託運費用
    }

    # 方法 1：從 flight.extensions 裡找（常見格式）
    all_extensions = list(flight.get("extensions", []))
    for leg in legs:
        all_extensions.extend(leg.get("extensions", []))

    for ext in all_extensions:
        if not ext:
            continue
        ext_lower = ext.lower()

        # 手提行李
        if "carry-on" in ext_lower or "carry on" in ext_lower or "cabin" in ext_lower:
            baggage["carry_on"] = ext
        # 託運行李（免費）
        elif ("checked" in ext_lower or "baggage" in ext_lower) and ("free" in ext_lower or "included" in ext_lower):
            baggage["checked_bag"] = ext
        # 託運行李（付費）
        elif "checked" in ext_lower or ("bag" in ext_lower and ("fee" in ext_lower or "$" in ext_lower or "charge" in ext_lower)):
            baggage["checked_bag_fee"] = ext
        # 沒有託運
        elif "no checked" in ext_lower:
            baggage["checked_bag"] = ext

    # 方法 2：從 flight 頂層的 baggage 欄位
    if "carry_on_bag" in flight:
        info = flight["carry_on_bag"]
        if isinstance(info, dict):
            baggage["carry_on"] = info.get("description", str(info))
        elif isinstance(info, list) and info:
            baggage["carry_on"] = str(info[0])

    if "checked_bag" in flight:
        info = flight["checked_bag"]
        if isinstance(info, dict):
            desc = info.get("description", "")
            price = info.get("price")
            if price:
                baggage["checked_bag_fee"] = f"{desc} ({price})" if desc else str(price)
            else:
                baggage["checked_bag"] = desc or str(info)
        elif isinstance(info, list) and info:
            baggage["checked_bag"] = str(info[0])

    return baggage


def format_minutes(minutes):
    """將分鐘數轉為易讀格式"""
    if not minutes:
        return ""
    h = minutes // 60
    m = minutes % 60
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
        raw = search_flights(origin, destination, depart_date,
                             return_date=return_date, adults=adults,
                             nonstop=nonstop)

        # 檢查 API 錯誤
        if "error" in raw:
            return jsonify({"error": f"API 錯誤：{raw['error']}"}), 500

        results = parse_serpapi_results(raw, origin, destination, depart_date)
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
    會搜未來 60 天，取樣 8 個出發日 × 搭配回程（3/5/7 天後），
    幫用戶找到預算內最划算的組合。
    """
    data = request.json
    origin = data.get("origin", "").strip().upper()
    destination = data.get("destination", "").strip().upper()
    budget = int(data.get("budget", 999999))
    adults = int(data.get("adults", 1))
    nonstop = data.get("nonstop", False)
    trip_days_options = [int(d) for d in data.get("trip_days", [3, 5, 7])]
    search_months = int(data.get("search_months", 2))  # 搜尋幾個月

    if not origin or not destination:
        return jsonify({"error": "請填寫出發地和目的地"}), 400
    if budget <= 0:
        return jsonify({"error": "請輸入有效的預算金額"}), 400

    # 根據搜尋範圍，在未來 N 個月內均勻取樣 8~10 個出發日
    today = datetime.now()
    total_days_range = search_months * 30
    num_samples = min(10, max(6, search_months * 3))  # 2月=6, 3月=9, 6月=10, 12月=10
    step = max(total_days_range // num_samples, 7)

    sample_depart_dates = []
    for i in range(num_samples):
        d = today + timedelta(days=7 + i * step)
        if d > today + timedelta(days=total_days_range):
            break
        sample_depart_dates.append(d)

    all_results = []
    searched_combos = []
    errors = []

    for dep_date in sample_depart_dates:
        for trip_days in trip_days_options:
            ret_date = dep_date + timedelta(days=trip_days)
            dep_str = dep_date.strftime("%Y-%m-%d")
            ret_str = ret_date.strftime("%Y-%m-%d")
            combo_label = f"{dep_str} ~ {ret_str}（{trip_days}天）"
            searched_combos.append(combo_label)

            try:
                raw = search_flights(
                    origin, destination, dep_str,
                    return_date=ret_str, adults=adults, nonstop=nonstop
                )
                if "error" in raw:
                    errors.append(f"{combo_label}: {raw['error']}")
                    continue

                results = parse_serpapi_results(raw, origin, destination, dep_str)

                for r in results:
                    r["search_date"] = dep_str
                    r["return_date"] = ret_str
                    r["trip_days"] = trip_days
                    r["combo_label"] = f"{dep_str} 出發 → {ret_str} 回來（{trip_days}天）"

                all_results.extend(results)
                time.sleep(0.5)

            except Exception as e:
                errors.append(f"{combo_label}: {str(e)}")
                continue

    # 篩選預算內
    filtered = [r for r in all_results if r["price"] <= budget]
    filtered.sort(key=lambda x: x["price"])

    # 如果預算內沒有，就回傳全部最便宜的（讓用戶知道最低價是多少）
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
        # 亞洲 × 6
        "NRT": {"name": "東京", "region": "日本"},
        "KIX": {"name": "大阪", "region": "日本"},
        "ICN": {"name": "首爾", "region": "韓國"},
        "BKK": {"name": "曼谷", "region": "泰國"},
        "SGN": {"name": "胡志明市", "region": "越南"},
        "SIN": {"name": "新加坡", "region": "新加坡"},
        # 美洲 × 2
        "LAX": {"name": "洛杉磯", "region": "美國"},
        "JFK": {"name": "紐約", "region": "美國"},
        # 歐洲 × 2
        "CDG": {"name": "巴黎", "region": "法國"},
        "LHR": {"name": "倫敦", "region": "英國"},
    }

    # 排除自己
    destinations = {k: v for k, v in POPULAR_DESTINATIONS.items() if k != origin}

    # 只搜一個日期（省 API 額度）：未來 3 週
    today = datetime.now()
    sample_dates = [(today + timedelta(days=21)).strftime("%Y-%m-%d")]

    results = []
    errors = []

    for dest_code, dest_info in destinations.items():
        cheapest = None
        cheapest_date = None

        for dep_date in sample_dates:
            try:
                raw = search_flights(origin, dest_code, dep_date, adults=adults)
                if "error" in raw:
                    continue

                # 只看最便宜的
                all_flights = raw.get("best_flights", []) + raw.get("other_flights", [])
                for f in all_flights:
                    price = f.get("price")
                    if price and (cheapest is None or price < cheapest):
                        cheapest = price
                        cheapest_date = dep_date

                        # 取航班資訊
                        legs = f.get("flights", [])
                        if legs:
                            first_leg = legs[0]
                            cheapest_info = {
                                "carrier": first_leg.get("airline", ""),
                                "duration": f.get("total_duration", 0),
                                "stops": len(legs) - 1,
                            }

                time.sleep(0.3)
            except Exception as e:
                errors.append(f"{dest_code}: {str(e)}")
                continue

        if cheapest is not None:
            # 訂票連結
            google_url = f"https://www.google.com/travel/flights?q=Flights+to+{dest_code}+from+{origin}"
            trip_url = f"https://www.trip.com/flights/{origin.lower()}-to-{dest_code.lower()}/tickets-{origin.lower()}-{dest_code.lower()}?Allianceid=8060886&SID=304954294"
            agoda_url = f"https://www.agoda.com/flights/results?origin={origin}&destination={dest_code}&locale=zh-tw&curr=TWD"

            results.append({
                "destination_code": dest_code,
                "destination_name": dest_info["name"],
                "region": dest_info["region"],
                "cheapest_price": cheapest,
                "cheapest_date": cheapest_date,
                "carrier": cheapest_info.get("carrier", ""),
                "duration": format_minutes(cheapest_info.get("duration", 0)),
                "stops": cheapest_info.get("stops", 0),
                "in_budget": cheapest <= budget,
                "google_url": google_url,
                "trip_url": trip_url,
                "agoda_url": agoda_url,
            })

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

    # 精確匹配 IATA 代碼優先
    results = []
    if keyword in AIRPORTS_DB:
        results.append(AIRPORTS_DB[keyword])

    # 模糊搜尋名稱、城市、國家
    for code, a in AIRPORTS_DB.items():
        if len(results) >= 10:
            break
        if code == keyword:
            continue  # 已加過
        searchable = f"{a['code']} {a['name']} {a['city']} {a['country']}".upper()
        if keyword in searchable:
            results.append(a)
    return jsonify(results)


@app.route("/api/config", methods=["GET"])
def api_config_status():
    """檢查 API 設定狀態"""
    cfg = load_config()
    configured = bool(cfg.get("serpapi_key"))
    return jsonify({"configured": configured})


@app.route("/api/config", methods=["POST"])
def api_config_save():
    """儲存 API 設定（僅本機模式可用）"""
    if os.environ.get("SERPAPI_KEY"):
        return jsonify({"ok": True, "msg": "雲端模式，API Key 已透過環境變數設定"})
    data = request.json
    cfg = load_config()
    cfg["serpapi_key"] = data.get("api_key", "").strip()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return jsonify({"ok": True})


if __name__ == "__main__":
    print("=" * 50)
    print("  機票比價系統 啟動中...")
    print("  請在瀏覽器開啟 http://localhost:5000")
    print("=" * 50)
    app.run(debug=True, port=5000)
