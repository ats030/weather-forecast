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
# LLM生成
# =========================
def generate_ai_output(today_data, profile):
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
                    "options":{"temperature":0.7,"num_predict":800}
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
            logging.error(f"LLM生成例外: {e} (attempt {attempt})")
            update_paragraph_stats(False)
            time.sleep(1)

    logging.error("生成失敗")
    return "生成失敗"

# =========================
# メッセージ構築
# =========================
def build_daily_message(today_data, profile):
    text = generate_ai_output(today_data, profile)
    return f"【今日の天気】\n\n{text}\n\n更新: {datetime.datetime.now(JST)}"

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

    msg = build_daily_message(today_data, profile)
    send(msg)

if __name__ == "__main__":
    main()