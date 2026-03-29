# -*- coding: utf-8 -*-
import datetime
import logging
import time
import requests
import os
import json
from weather_lib import *

JST = datetime.timezone(datetime.timedelta(hours=9))

# =========================
# 曜日変換
# =========================
WEEKDAY_MAP = {
    "Monday": "月曜日",
    "Tuesday": "火曜日",
    "Wednesday": "水曜日",
    "Thursday": "木曜日",
    "Friday": "金曜日",
    "Saturday": "土曜日",
    "Sunday": "日曜日"
}

# =========================
# 日ごとグループ
# =========================
def group_week_by_day(week_data):
    days = {}
    for d in week_data:
        day_date = datetime.datetime.fromtimestamp(d["dt"], JST).date()
        days.setdefault(day_date, []).append(d)
    return [(k, days[k]) for k in sorted(days.keys())]

# =========================
# 圧縮（曜日追加）
# =========================
def compress_day_data(day_date, day_list, profile):

    morning, day, night = split_by_time(day_list)

    m_block = evaluate_block(morning)
    d_block = evaluate_block(day)
    n_block = evaluate_block(night)

    weekday_en = day_date.strftime("%A")
    weekday = WEEKDAY_MAP.get(weekday_en, weekday_en)

    return {
        "date": str(day_date),
        "weekday": weekday,
        "morning": categorize_block(m_block),
        "day": categorize_block(d_block),
        "night": categorize_block(n_block),
        "clothing": {
            "morning": clothing_engine(m_block, profile),
            "day": clothing_engine(d_block, profile),
            "night": clothing_engine(n_block, profile)
        }
    }

# =========================
# LLM生成
# =========================
def generate_weekly_ai_output(week_data, profile):

    raw_url = os.getenv("OLLAMA_URL")
    if not raw_url:
        return "生成不可"

    template = load_template("CONTEXT_WEEKLY")
    if not template:
        return "テンプレート読み込み失敗"

    grouped = group_week_by_day(week_data)

    compressed = [
        compress_day_data(day_date, day_list, profile)
        for day_date, day_list in grouped
    ]

    prompt = template + "\n\nWEATHER ANALYSIS:\n" + json.dumps(compressed, ensure_ascii=False)

    failure_rate = get_failure_rate()
    max_retry = min(6, max(3, int(3 + failure_rate*10)))

    for attempt in range(1, max_retry+1):
        try:
            res = requests.post(
                f"{normalize_ollama_url(raw_url)}/api/generate",
                json={
                    "model":"gemma3:4b",
                    "prompt":prompt,
                    "stream":False,
                    "options":{"temperature":0.7,"num_predict":1200}
                },
                timeout=180
            )

            text = res.json().get("response","").strip()

            if text and validate_output(text):
                update_paragraph_stats(True)
                return text
            else:
                logging.warning(f"フォーマット不正 (attempt {attempt})")
                update_paragraph_stats(False)

        except Exception as e:
            logging.error(f"LLM生成例外: {e}")
            update_paragraph_stats(False)
            time.sleep(1)

    logging.error("生成失敗")
    return "生成失敗"

def build_weekly_message(week_data, profile):
    text = generate_weekly_ai_output(week_data, profile)
    return f"【今週の天気】\n\n{text}\n\n更新: {datetime.datetime.now(JST)}"

def main():
    profile = parse_user_profile()
    address = get_user_address()

    lat, lon = geocode_address(address)
    if lat is None or lon is None:
        logging.error("緯度経度取得失敗")
        return

    data = fetch_with_fallback(lat, lon)
    if not data:
        logging.error("天気取得失敗")
        return

    week_data = extract_week_data(data)
    if not week_data:
        logging.error("週間データなし")
        return

    msg = build_weekly_message(week_data, profile)
    send(msg)

if __name__ == "__main__":
    main()