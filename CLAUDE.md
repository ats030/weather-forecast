# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

AIを活用した天気予報アプリケーション。パーソナライズされた日次・週次の天気予報と服装提案を生成し、Discordに送信します。

## 実行コマンド

```bash
# 日次予報
python3 forecast_daily.py

# 週次予報
python3 forecast_weekly.py
```

## 環境変数

`.env` ファイルは **スクリプトを実行するカレントディレクトリ** に配置する（`find_dotenv(usecwd=True)` を使用）。

| 変数 | 説明 |
|------|------|
| `OPENWEATHER_API_KEY` | OpenWeatherMap APIキー |
| `DISCORD_WEBHOOK_URL` | Discord Webhook URL（未設定時はログ出力のみ） |
| `OLLAMA_URL` | ローカルOllamaサーバーのエンドポイント（例: `http://localhost:11434`） |
| `USER_ADDRESS` | ユーザーの住所（ジオコーディング用） |
| `USER_COLD_TOLERANCE` | 寒さ耐性: `弱い` または `普通`（「弱い」で体感温度-2℃補正） |
| `USER_HEAT_TOLERANCE` | 暑さ耐性: `弱い` または `普通`（「弱い」で体感温度+2℃補正） |

## 依存パッケージ

```bash
pip install requests python-dotenv
```

## アーキテクチャ

### コアファイル

- **weather_lib.py** - 全共有ロジック。`forecast_daily.py` と `forecast_weekly.py` は `from weather_lib import *` でインポート
- **forecast_daily.py** - CONTEXT_DAILY.md テンプレートを使用した日次予報生成
- **forecast_weekly.py** - CONTEXT_WEEKLY.md テンプレートを使用した週次予報生成
- **CONTEXT_DAILY.md / CONTEXT_WEEKLY.md** - Ollama に送るシステムプロンプト（LLMの出力フォーマットと表現ルールを定義）

### データフロー

```
住所 → 緯度経度（Nominatim）
緯度経度 → 3時間予報データ（OpenWeatherMap /forecast）
緯度経度 → UV指数データ（OpenWeatherMap /uvi/forecast）※取得失敗時はNone
↓
時間帯別に分割（朝 5-10時 / 昼 10-17時 / 夜 17-5時）
↓
evaluate_block() で各ブロックの統計値を計算
  └── UV指数は forecast_*.py 側でブロックに注入（朝・昼のみ有効、夜はNone）
↓
categorize_block() で全フィールドを日本語カテゴリ文字列に変換
clothing_engine() で服装提案テキストを生成
↓
CONTEXT_*.md テンプレート + JSON データ → Ollama LLM（gemma3:4b）
↓
6段落検証 → 不正ならリトライ（適応的リトライ回数）
↓
Discord Webhook 送信
```

### weather_lib.py の主要関数

| 関数 | 役割 |
|------|------|
| `evaluate_block(lst)` | 3時間予報データのリストから統計値ブロックを生成。`_EMPTY_BLOCK` をデフォルト値として使用 |
| `categorize_block(block)` | 数値ブロックを全フィールド日本語カテゴリに変換（LLMへの入力） |
| `clothing_engine(block, profile)` | 気象値と耐性プロファイルから服装提案テキストを生成 |
| `call_ollama(raw_url, prompt, num_predict)` | Ollamaへの共通リトライロジック（適応的リトライ回数） |
| `fetch_uv_daily(lat, lon)` | `/data/2.5/uvi/forecast` からUV指数を取得。`{日付文字列: uv値}` の辞書を返す |
| `fetch_with_fallback(lat, lon)` | 天気データ取得。失敗時は逆ジオコーディングで再試行 |

### evaluate_block が処理するフィールド

`evaluate_block()` が返すブロックには以下のフィールドが含まれる（すべて数値またはNone）:

| フィールド | 算出方法 | 備考 |
|-----------|---------|------|
| `feels_like` | 平均 | ℃ |
| `humidity` | 平均 | % |
| `wind` | 平均 | m/s |
| `rain` | 合計 | mm (3h) |
| `sky` | 最頻値 | `weather[0].main` の文字列（例: "Clear", "Snow"） |
| `pop` | 平均 | 0-1スケール |
| `snow` | 合計 | mm (3h) |
| `wind_gust` | 最大値 | m/s、データなし時はNone |
| `dew_point` | Magnus公式で計算 | temp + humidity から算出、℃ |
| `visibility` | 最小値 | m、データなし時はNone |
| `uv_index` | 外部注入 | `evaluate_block()` では常にNone。`forecast_*.py` 側で `fetch_uv_daily()` の結果を代入 |

### clothing_engine の判定優先順位

`options` リストに最大2件まで追加（ベースフレーズ1件 + オプション最大2件）:

1. 雷雨（`sky == "Thunderstorm"`）
2. 降雪（`snow > 0`）
3. 雨 または 降水確率高（`rain > 0 or pop >= 0.5`）
4. 突風・強風（`wind_gust > 10` または `wind > 7`）
5. 紫外線（`uv_index >= 6`）
6. 蒸し暑さ（露点温度 > 21℃ → `humidity > 75` にフォールバック）

### 主要な設計パターン

- **適応的リトライ**: `PARAGRAPH_HISTORY`（maxlen=50）の失敗率に基づき、リトライ回数を 3〜6 回の範囲で動的調整
- **フォールバックジオコーディング**: `fetch_with_fallback()` が失敗した場合、逆ジオコーディングで市区町村名を取得して再試行
- **UV注入パターン**: `uv_index` は `/forecast` APIに含まれないため、`forecast_*.py` がブロック生成後に手動で注入する。夜ブロックは常に `None`
- **`_EMPTY_BLOCK` センチネル**: `evaluate_block()` の空/例外時リターンは `dict(_EMPTY_BLOCK)` で統一。新フィールド追加時はここも更新が必要

## LLM出力ルール

プロンプトは厳格なフォーマットを強制:
- 必ず6段落（挨拶、朝、昼、夜、まとめ、結び）、空行で区切る
- 番号、ラベル、箇条書き、見出しは禁止
- 気温の数値ではなく体感表現を使用
- 地名・ユーザープロファイル情報は出力に含めない
- LLMに渡すデータはすべて日本語カテゴリ文字列（数値は渡さない）
- `"データなし"` または `"不明"` のフィールドはLLMに言及させない
