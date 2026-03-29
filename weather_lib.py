# -*- coding: utf-8 -*-
import os
import requests
import datetime
import re
import random
from dotenv import load_dotenv
import logging
import time
from collections import deque

ENV_PATH = os.path.expanduser("~/venv/venv_test/.env")
load_dotenv(ENV_PATH)

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
    today = datetime.datetime.now(JST).date()
    return [
        d for d in data.get("list", [])
        if datetime.datetime.fromtimestamp(d["dt"], JST).date() == today
    ]

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
def evaluate_block(lst):
    if not lst:
        return {
            "feels_like": None,
            "humidity": None,
            "wind": None,
            "rain": 0
        }

    try:
        feels = [d["main"]["feels_like"] for d in lst if "main" in d]
        humidity = [d["main"]["humidity"] for d in lst if "main" in d]
        wind = [d["wind"]["speed"] for d in lst if "wind" in d]
        rain = sum(d.get("rain", {}).get("3h", 0) for d in lst)

        return {
            "feels_like": sum(feels)/len(feels) if feels else None,
            "humidity": sum(humidity)/len(humidity) if humidity else None,
            "wind": sum(wind)/len(wind) if wind else None,
            "rain": rain
        }

    except Exception as e:
        logging.warning(f"evaluate_block失敗: {e}")
        return {
            "feels_like": None,
            "humidity": None,
            "wind": None,
            "rain": 0
        }

# =========================
# データ前処理（数値→カテゴリ変換）
# =========================
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
        "feels_like": categorize_feels_like(block.get("feels_like")),
        "humidity": categorize_humidity(block.get("humidity")),
        "wind": categorize_wind(block.get("wind")),
        "rain": categorize_rain(block.get("rain", 0))
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
    ]
}

# =========================
# 服装判定（バリエーション対応）
# =========================
def clothing_engine(block, profile):
    if not block or block["feels_like"] is None:
        return "服装の判断が難しい状況です"

    feels = block["feels_like"] + profile["cold"] - profile["heat"]
    humidity = block["humidity"] or 0
    wind = block["wind"] or 0
    rain = block["rain"] or 0

    if feels >= 30:
        base = random.choice(CLOTHING_PHRASES["very_hot"])
    elif feels >= 24:
        base = random.choice(CLOTHING_PHRASES["hot"])
    elif feels >= 18:
        base = random.choice(CLOTHING_PHRASES["mild"])
    elif feels >= 12:
        base = random.choice(CLOTHING_PHRASES["cool"])
    else:
        base = random.choice(CLOTHING_PHRASES["cold"])

    options = []

    if humidity > 75:
        options.append(random.choice(CLOTHING_PHRASES["humid"]))
    if wind > 7:
        options.append(random.choice(CLOTHING_PHRASES["windy"]))
    if rain > 0:
        options.append(random.choice(CLOTHING_PHRASES["rainy"]))

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