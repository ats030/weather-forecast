# -*- coding: utf-8 -*-
import datetime
import logging
import os
import json
from weather_lib import *

# =========================
# LLM生成
# =========================
def generate_ai_output(today_data, profile, uv_today=None):
    raw_url = os.getenv("OLLAMA_URL")
    if not raw_url:
        return "生成不可"

    template = load_template("CONTEXT_DAILY")
    if not template:
        return "テンプレート読み込み失敗"

    morning, day, night = split_by_time(today_data)

    m_block = evaluate_block(morning)
    d_block = evaluate_block(day)
    n_block = evaluate_block(night)

    # UV注入（朝・昼のみ有効、夜はNone）
    m_block["uv_index"] = uv_today
    d_block["uv_index"] = uv_today
    n_block["uv_index"] = None

    clothes = {
        "morning": clothing_engine(m_block, profile),
        "day": clothing_engine(d_block, profile),
        "night": clothing_engine(n_block, profile)
    }

    # =========================
    # JSON化（カテゴリ変換適用）
    # =========================
    analysis = {
        "morning": categorize_block(m_block),
        "day": categorize_block(d_block),
        "night": categorize_block(n_block),
        "clothing": clothes
    }

    prompt = template + "\n\nWEATHER ANALYSIS:\n" + json.dumps(analysis, ensure_ascii=False)
    return call_ollama(raw_url, prompt, num_predict=800)

# =========================
# メッセージ構築
# =========================
def build_daily_message(today_data, profile, uv_today=None):
    text = generate_ai_output(today_data, profile, uv_today)
    data_date = datetime.datetime.fromtimestamp(today_data[0]["dt"], JST).date()
    title = "今日の天気" if data_date == datetime.datetime.now(JST).date() else "明日の天気"
    return f"【{title}】\n\n{text}\n\n更新: {datetime.datetime.now(JST)}"

# =========================
# main
# =========================
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

    today_data = extract_today_data(data)
    if not today_data:
        logging.warning("今日のデータなし")
        return

    uv_data = fetch_uv_daily(lat, lon)
    uv_today = uv_data.get(str(datetime.datetime.now(JST).date()))

    msg = build_daily_message(today_data, profile, uv_today)
    send(msg)

if __name__ == "__main__":
    main()
