# -*- coding: utf-8 -*-
import datetime
import logging
import os
import json
from weather_lib import *

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
# 圧縮（曜日・UV追加）
# =========================
def compress_day_data(day_date, day_list, profile, uv_today=None):

    morning, day, night = split_by_time(day_list)

    m_block = evaluate_block(morning)
    d_block = evaluate_block(day)
    n_block = evaluate_block(night)

    # UV注入（朝・昼のみ有効、夜はNone）
    m_block["uv_index"] = uv_today
    d_block["uv_index"] = uv_today
    n_block["uv_index"] = None

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
def generate_weekly_ai_output(week_data, profile, uv_data=None):

    raw_url = os.getenv("OLLAMA_URL")
    if not raw_url:
        return "生成不可"

    template = load_template("CONTEXT_WEEKLY")
    if not template:
        return "テンプレート読み込み失敗"

    uv_data = uv_data or {}
    grouped = group_week_by_day(week_data)

    compressed = [
        compress_day_data(day_date, day_list, profile, uv_data.get(str(day_date)))
        for day_date, day_list in grouped
    ]

    prompt = template + "\n\nWEATHER ANALYSIS:\n" + json.dumps(compressed, ensure_ascii=False)
    return call_ollama(raw_url, prompt, num_predict=1200)

def build_weekly_message(week_data, profile, uv_data=None):
    text = generate_weekly_ai_output(week_data, profile, uv_data)
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

    uv_data = fetch_uv_daily(lat, lon)

    msg = build_weekly_message(week_data, profile, uv_data)
    send(msg)

if __name__ == "__main__":
    main()
