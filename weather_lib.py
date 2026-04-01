# -*- coding: utf-8 -*-
import os
import json
import requests
import datetime
import math
import random
from dotenv import load_dotenv, find_dotenv
import logging
import time
from collections import deque, Counter

load_dotenv(find_dotenv(usecwd=True))

JST = datetime.timezone(datetime.timedelta(hours=9))

# =========================
# ログ設定
# =========================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# =========================
# 段落崩れ率統計用
# =========================
PARAGRAPH_HISTORY = deque(maxlen=50)

def update_paragraph_stats(success: bool):
    PARAGRAPH_HISTORY.append(1 if success else 0)

def get_failure_rate():
    if not PARAGRAPH_HISTORY:
        return 0.0
    failures = PARAGRAPH_HISTORY.count(0)
    return failures / len(PARAGRAPH_HISTORY)

# =========================
# ユーザープロファイル（環境変数から取得）
# =========================
def get_user_address():
    """環境変数から住所を取得"""
    return os.getenv("USER_ADDRESS")

def parse_user_profile():
    """環境変数からclothing_engine用のプロファイルを作成"""
    profile = {"cold": 0, "heat": 0}

    if os.getenv("USER_COLD_TOLERANCE") == "弱い":
        profile["cold"] = -2
    if os.getenv("USER_HEAT_TOLERANCE") == "弱い":
        profile["heat"] = -2

    return profile

# =========================
# Geocoding
# =========================
def geocode_address(address: str):
    try:
        res = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": address, "format": "json", "limit": 1},
            headers={"User-Agent": "weather-app"},
            timeout=10
        )
        data = res.json()
        if not data:
            return None, None
        return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as e:
        logging.error(f"Geocoding失敗: {e}")
        return None, None

def reverse_geocode(lat, lon):
    try:
        res = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lon, "format": "json"},
            headers={"User-Agent": "weather-app"},
            timeout=10
        )
        data = res.json()
        address = data.get("address", {})
        return address.get("city") or address.get("town") or address.get("village")
    except Exception as e:
        logging.warning(f"Reverse Geocoding失敗: {e}")
        return None

# =========================
# Weather API
# =========================
def fetch_forecast(lat, lon):
    api_key = os.getenv("OPENWEATHER_API_KEY")
    if not api_key or lat is None:
        return None
    try:
        res = requests.get(
            "https://api.openweathermap.org/data/2.5/forecast",
            params={"lat": lat, "lon": lon, "appid": api_key, "units": "metric", "lang": "ja"},
            timeout=10
        )
        return res.json() if res.status_code == 200 else None
    except Exception as e:
        logging.error(f"Forecast取得失敗: {e}")
        return None

def fetch_uv_daily(lat, lon):
    """UV指数の日別予報を取得 ({date文字列: uv値} の辞書を返す)"""
    api_key = os.getenv("OPENWEATHER_API_KEY")
    if not api_key or lat is None:
        return {}
    try:
        res = requests.get(
            "https://api.openweathermap.org/data/2.5/uvi/forecast",
            params={"lat": lat, "lon": lon, "appid": api_key, "cnt": 8},
            timeout=10
        )
        if res.status_code != 200:
            logging.warning(f"UV取得失敗: HTTP {res.status_code}")
            return {}
        return {
            str(datetime.datetime.fromtimestamp(item["date"], JST).date()): item["value"]
            for item in res.json()
        }
    except Exception as e:
        logging.warning(f"UV取得失敗: {e}")
        return {}

def fetch_with_fallback(lat, lon):
    data = fetch_forecast(lat, lon)
    if data:
        return data
    city = reverse_geocode(lat, lon)
    if not city:
        return None
    lat2, lon2 = geocode_address(city)
    return fetch_forecast(lat2, lon2)

# =========================
# 天気データ処理
# =========================
def extract_today_data(data):
    """当日の予報データを返す。当日分が尽きている場合は翌日（最初の利用可能な日）を返す。"""
    today = datetime.datetime.now(JST).date()
    result = [
        d for d in data.get("list", [])
        if datetime.datetime.fromtimestamp(d["dt"], JST).date() == today
    ]
    if not result:
        # 深夜など当日スロットが尽きた場合、次の利用可能な日を使用
        dates = [datetime.datetime.fromtimestamp(d["dt"], JST).date() for d in data.get("list", [])]
        next_date = min(dates) if dates else None
        if next_date:
            result = [
                d for d in data.get("list", [])
                if datetime.datetime.fromtimestamp(d["dt"], JST).date() == next_date
            ]
    return result

def extract_week_data(data):
    today = datetime.datetime.now(JST).date()
    week_end = today + datetime.timedelta(days=6)
    return [
        d for d in data.get("list", [])
        if today <= datetime.datetime.fromtimestamp(d["dt"], JST).date() <= week_end
    ]

def split_by_time(today_data):
    morning, day, night = [], [], []
    for d in today_data:
        hour = datetime.datetime.fromtimestamp(d["dt"], JST).hour
        if 5 <= hour < 10:
            morning.append(d)
        elif 10 <= hour < 17:
            day.append(d)
        else:
            night.append(d)
    return morning, day, night

# =========================
# 安定化された評価関数（重要修正）
# =========================
def _calc_dew_point(temp, humidity):
    """Magnus公式による露点温度計算（℃）"""
    if temp is None or humidity is None or humidity <= 0:
        return None
    a, b = 17.625, 243.04
    gamma = math.log(max(humidity, 1) / 100.0) + a * temp / (b + temp)
    return b * gamma / (a - gamma)

_EMPTY_BLOCK = {
    "feels_like": None, "humidity": None, "wind": None, "rain": 0,
    "sky": None, "pop": 0.0, "snow": 0, "wind_gust": None,
    "dew_point": None, "visibility": None, "uv_index": None
}

def evaluate_block(lst):
    if not lst:
        return dict(_EMPTY_BLOCK)

    try:
        feels    = [d["main"]["feels_like"] for d in lst if "main" in d]
        temp     = [d["main"]["temp"]        for d in lst if "main" in d]
        humidity = [d["main"]["humidity"]    for d in lst if "main" in d]
        wind     = [d["wind"]["speed"]       for d in lst if "wind" in d]
        rain     = sum(d.get("rain", {}).get("3h", 0) for d in lst)

        sky_list = [d["weather"][0]["main"] for d in lst if "weather" in d and d["weather"]]
        sky      = Counter(sky_list).most_common(1)[0][0] if sky_list else None

        pop_list = [d["pop"] for d in lst if "pop" in d]
        pop      = sum(pop_list) / len(pop_list) if pop_list else 0.0

        snow     = sum(d.get("snow", {}).get("3h", 0) for d in lst)

        gust_list  = [d["wind"]["gust"] for d in lst if "wind" in d and "gust" in d["wind"]]
        wind_gust  = max(gust_list) if gust_list else None

        vis_list   = [d["visibility"] for d in lst if "visibility" in d]
        visibility = min(vis_list) if vis_list else None

        avg_temp  = sum(temp)     / len(temp)     if temp     else None
        avg_hum   = sum(humidity) / len(humidity) if humidity else None
        dew_point = _calc_dew_point(avg_temp, avg_hum)

        return {
            "feels_like": sum(feels)/len(feels) if feels else None,
            "humidity":   avg_hum,
            "wind":       sum(wind)/len(wind) if wind else None,
            "rain":       rain,
            "sky":        sky,
            "pop":        pop,
            "snow":       snow,
            "wind_gust":  wind_gust,
            "dew_point":  dew_point,
            "visibility": visibility,
            "uv_index":   None,   # 外部から注入（fetch_uv_daily）
        }

    except Exception as e:
        logging.warning(f"evaluate_block失敗: {e}")
        return dict(_EMPTY_BLOCK)

# =========================
# データ前処理（数値→カテゴリ変換）
# =========================
def categorize_sky(sky):
    """天気状態をカテゴリに変換"""
    if sky is None: return "不明"
    mapping = {
        "Clear": "晴れ", "Clouds": "曇り", "Rain": "雨", "Drizzle": "小雨",
        "Thunderstorm": "雷雨", "Snow": "雪", "Mist": "霧", "Fog": "霧",
        "Haze": "霞", "Smoke": "煙霧", "Dust": "砂塵", "Sand": "砂塵",
        "Ash": "火山灰", "Squall": "スコール", "Tornado": "竜巻",
    }
    return mapping.get(sky, sky)

def categorize_pop(pop):
    """降水確率をカテゴリに変換 (0-1スケール入力)"""
    if pop is None: return "不明"
    pct = pop * 100
    if pct >= 80: return "非常に高い"
    if pct >= 60: return "高い"
    if pct >= 40: return "やや高い"
    if pct >= 20: return "低め"
    return "ほぼなし"

def categorize_snow(amount):
    """降雪量をカテゴリに変換"""
    if amount >= 5: return "大雪"
    if amount >= 1: return "雪"
    if amount > 0:  return "小雪"
    return "なし"

def categorize_dew_point(td):
    """露点温度をカテゴリに変換（蒸し暑さの指標）"""
    if td is None: return "不明"
    if td >= 24: return "非常に蒸し暑い"
    if td >= 21: return "蒸し暑い"
    if td >= 18: return "やや蒸し暑い"
    if td >= 12: return "快適"
    if td >= 6:  return "乾燥気味"
    return "乾燥"

def categorize_visibility(vis):
    """視程をカテゴリに変換（m単位）"""
    if vis is None: return "不明"
    if vis >= 8000: return "良好"
    if vis >= 4000: return "普通"
    if vis >= 1000: return "やや不良（霧・煙）"
    return "不良（濃霧）"

def categorize_uv(uv):
    """UV指数をカテゴリに変換"""
    if uv is None: return "データなし"
    if uv >= 11: return "極端に強い"
    if uv >= 8:  return "非常に強い"
    if uv >= 6:  return "強い"
    if uv >= 3:  return "中程度"
    if uv >= 1:  return "弱い"
    return "ほぼなし"

def categorize_feels_like(temp):
    """体感温度をカテゴリに変換"""
    if temp is None: return "不明"
    if temp >= 30: return "とても暑い"
    if temp >= 25: return "暑い"
    if temp >= 20: return "暖かい"
    if temp >= 15: return "過ごしやすい"
    if temp >= 10: return "肌寒い"
    return "寒い"

def categorize_humidity(hum):
    """湿度をカテゴリに変換"""
    if hum is None: return "不明"
    if hum >= 80: return "非常に蒸し暑い"
    if hum >= 70: return "蒸し暑い"
    if hum >= 50: return "普通"
    if hum >= 30: return "乾燥気味"
    return "乾燥している"

def categorize_wind(speed):
    """風速をカテゴリに変換"""
    if speed is None: return "不明"
    if speed >= 10: return "非常に強い"
    if speed >= 7: return "強め"
    if speed >= 4: return "やや強い"
    if speed >= 2: return "穏やか"
    return "ほぼ無風"

def categorize_rain(amount):
    """降水量をカテゴリに変換"""
    if amount >= 10: return "強い雨"
    if amount >= 5: return "雨"
    if amount > 0: return "小雨"
    return "なし"

def categorize_block(block):
    """ブロック全体をカテゴリ化"""
    return {
        "feels_like":  categorize_feels_like(block.get("feels_like")),
        "humidity":    categorize_humidity(block.get("humidity")),
        "wind":        categorize_wind(block.get("wind")),
        "rain":        categorize_rain(block.get("rain", 0)),
        "sky":         categorize_sky(block.get("sky")),
        "pop":         categorize_pop(block.get("pop", 0.0)),
        "snow":        categorize_snow(block.get("snow", 0)),
        "wind_gust":   categorize_wind(block.get("wind_gust")) if block.get("wind_gust") is not None else "データなし",
        "dew_point":   categorize_dew_point(block.get("dew_point")),
        "visibility":  categorize_visibility(block.get("visibility")),
        "uv_index":    categorize_uv(block.get("uv_index")),
    }

# =========================
# 服装表現のバリエーション
# =========================
CLOTHING_PHRASES = {
    "very_hot": [
        "半袖で快適に過ごせます",
        "涼しい服装がおすすめです",
        "半袖やノースリーブが快適です",
        "薄着で過ごすのがちょうど良さそうです"
    ],
    "hot": [
        "薄手の長袖がちょうど良いでしょう",
        "軽い素材の服装が快適です",
        "さらっとした素材の服がおすすめです",
        "通気性の良い服装が適しています"
    ],
    "mild": [
        "長袖が適しています",
        "長袖シャツ一枚で過ごせそうです",
        "薄手の長袖がちょうど良いです",
        "軽めの長袖で快適に過ごせます"
    ],
    "cool": [
        "軽い上着があると安心です",
        "薄手の羽織りものがあると便利です",
        "カーディガンや薄手のジャケットがおすすめです",
        "重ね着できる服装が良さそうです"
    ],
    "cold": [
        "しっかりした上着が必要です",
        "暖かいアウターを用意しましょう",
        "防寒対策をしっかりしておくと安心です",
        "厚手のコートやジャケットがおすすめです"
    ],
    "humid": [
        "蒸し暑さ対策として通気性の良い素材がおすすめです",
        "汗を吸いやすい素材を選ぶと快適です",
        "サラッとした素材が過ごしやすいです"
    ],
    "windy": [
        "風を防げる服装が役立ちます",
        "風よけになる上着があると安心です",
        "風の影響を受けにくい服装がおすすめです"
    ],
    "rainy": [
        "雨具の準備があると安心です",
        "折り畳み傘を持っておくと良いでしょう",
        "傘やレインコートを忘れずに"
    ],
    "snowy": [
        "防寒と滑り止め対策をしっかりと",
        "雪に備えた靴や服装がおすすめです",
        "足元に気をつけながら暖かくして出かけてください",
        "雪対応の靴と暖かいアウターが必要です"
    ],
    "thunderstorm": [
        "雷雨が予想されます。外出は最小限にしましょう",
        "傘だけでなく、落雷への注意も必要です",
        "激しい天気になる可能性があります。外出には注意を"
    ],
    "uv_high": [
        "日差しが強いので帽子や日焼け止めをお忘れなく",
        "紫外線が強めです。日焼け対策をしっかりと",
        "強い日差しに備えてUV対策をおすすめします"
    ]
}

# =========================
# 服装判定（バリエーション対応）
# =========================
def clothing_engine(block, profile):
    if not block or block["feels_like"] is None:
        return "服装の判断が難しい状況です"

    feels     = block["feels_like"] + profile["cold"] - profile["heat"]
    humidity  = block.get("humidity") or 0
    wind      = block.get("wind") or 0
    rain      = block.get("rain") or 0
    sky       = block.get("sky")
    pop       = block.get("pop") or 0.0
    snow      = block.get("snow") or 0
    wind_gust = block.get("wind_gust")

    # 降雪時は体感温度をcold方向に引き下げ
    effective_feels = min(feels, 11) if snow > 0 and feels >= 12 else feels

    if effective_feels >= 30:
        base = random.choice(CLOTHING_PHRASES["very_hot"])
    elif effective_feels >= 24:
        base = random.choice(CLOTHING_PHRASES["hot"])
    elif effective_feels >= 18:
        base = random.choice(CLOTHING_PHRASES["mild"])
    elif effective_feels >= 12:
        base = random.choice(CLOTHING_PHRASES["cool"])
    else:
        base = random.choice(CLOTHING_PHRASES["cold"])

    uv        = block.get("uv_index")
    dew_point = block.get("dew_point")

    options = []

    # 優先度順: 雷雨 > 雪 > 雨/降水確率 > 突風 > 紫外線 > 蒸し暑さ
    if sky == "Thunderstorm":
        options.append(random.choice(CLOTHING_PHRASES["thunderstorm"]))
    elif snow > 0:
        options.append(random.choice(CLOTHING_PHRASES["snowy"]))
    elif rain > 0 or pop >= 0.5:
        options.append(random.choice(CLOTHING_PHRASES["rainy"]))

    if len(options) < 2:
        if (wind_gust is not None and wind_gust > 10) or wind > 7:
            options.append(random.choice(CLOTHING_PHRASES["windy"]))

    if len(options) < 2 and uv is not None and uv >= 6:
        options.append(random.choice(CLOTHING_PHRASES["uv_high"]))

    if len(options) < 2:
        # 露点温度優先、なければ湿度で判定
        if dew_point is not None:
            if dew_point > 21:
                options.append(random.choice(CLOTHING_PHRASES["humid"]))
        elif humidity > 75:
            options.append(random.choice(CLOTHING_PHRASES["humid"]))

    if not options:
        return base
    elif len(options) == 1:
        return f"{base}。{options[0]}"
    else:
        return f"{base}。{options[0]}。{options[1]}"

# =========================
# Ollama URL正規化
# =========================
def normalize_ollama_url(url: str) -> str:
    if ":" not in url.replace("http://","").replace("https://",""):
        return url.rstrip("/") + ":11434"
    return url.rstrip("/")

# =========================
# 出力検証（6段落形式）
# =========================
def validate_output(text: str) -> bool:
    paragraphs = [p for p in text.strip().split("\n\n") if p.strip()]
    return len(paragraphs) == 6

# =========================
# テンプレートローダー
# =========================
def load_template(template_name: str) -> str:
    path = os.path.join(os.path.dirname(__file__), f"{template_name}.md")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception as e:
        logging.error(f"{template_name}.md読み込み失敗: {e}")
        return None

# =========================
# Ollama LLM呼び出し（共通リトライロジック）
# =========================
def call_ollama(raw_url: str, prompt: str, num_predict: int = 800) -> str:
    url = f"{normalize_ollama_url(raw_url)}/api/generate"
    failure_rate = get_failure_rate()
    max_retry = min(6, max(3, int(3 + failure_rate * 10)))

    for attempt in range(1, max_retry + 1):
        try:
            res = requests.post(
                url,
                json={
                    "model": "gemma3:4b",
                    "prompt": prompt,
                    "stream": True,
                    "options": {"temperature": 0.7, "num_predict": num_predict}
                },
                stream=True,
                timeout=(10, 60)
            )
            parts = []
            for line in res.iter_lines():
                if line:
                    chunk = json.loads(line)
                    parts.append(chunk.get("response", ""))
                    if chunk.get("done"):
                        break
            text = "".join(parts).strip()
            if text and validate_output(text):
                update_paragraph_stats(True)
                return text
            else:
                logging.warning(f"フォーマット不正 (attempt {attempt})")
                update_paragraph_stats(False)
        except Exception as e:
            logging.error(f"LLM生成例外: {e} (attempt {attempt})")
            update_paragraph_stats(False)
            time.sleep(1)

    logging.error("生成失敗")
    return "生成失敗"

# =========================
# Discord送信
# =========================
def send(msg):
    url = os.getenv("DISCORD_WEBHOOK_URL")
    if not url:
        logging.info(msg)
        return
    try:
        if len(msg) > 2000:
            chunks = [msg[i:i+1900] for i in range(0, len(msg), 1900)]
            for chunk in chunks:
                requests.post(url, json={"content": chunk})
        else:
            requests.post(url, json={"content": msg})
    except Exception as e:
        logging.error(f"Discord送信失敗: {e}")