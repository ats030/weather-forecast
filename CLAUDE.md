# CLAUDE.md

このファイルは、Claude Code (claude.ai/code) がこのリポジトリで作業する際のガイダンスを提供します。

## プロジェクト概要

AIを活用した天気予報アプリケーション。パーソナライズされた日次・週次の天気予報と服装提案を生成し、Discordに送信します。

## 実行コマンド

```bash
# 日次予報
python forecast_daily.py

# 週次予報
python forecast_weekly.py
```

## 必要な環境変数

`.env` ファイルに設定（パスは `weather_lib.py` の `ENV_PATH` で定義）:
- `OPENWEATHER_API_KEY` - OpenWeatherMap APIキー
- `DISCORD_WEBHOOK_URL` - Discord Webhook URL
- `OLLAMA_URL` - ローカルOllamaサーバーのエンドポイント（デフォルトポート: 11434）
- `USER_ADDRESS` - ユーザーの住所（ジオコーディング用）
- `USER_COLD_TOLERANCE` - 寒さ耐性: `弱い` または `普通`（「弱い」で体感温度-2℃補正）
- `USER_HEAT_TOLERANCE` - 暑さ耐性: `弱い` または `普通`（「弱い」で体感温度+2℃補正）

## 依存パッケージ

pipでインストール: `requests`, `python-dotenv`

## アーキテクチャ

### コアファイル

- **weather_lib.py** - 共通ライブラリ:
  - ジオコーディング（OpenStreetMap Nominatim API）
  - 天気データ取得（OpenWeatherMap API）
  - 時間帯分割（朝 5-10時、昼 10-17時、夜 17-5時）
  - 天気指標の評価（`evaluate_block`）
  - 数値→カテゴリ変換（`categorize_block`）- 体感温度・湿度・風速・降水量を日本語表現に変換
  - 服装提案（`clothing_engine`）
  - Discord送信
  - 段落崩れ率の統計（適応的リトライ用）

- **forecast_daily.py** - CONTEXT_DAILY.mdプロンプトテンプレートを使用した日次予報生成
- **forecast_weekly.py** - CONTEXT_WEEKLY.mdプロンプトテンプレートを使用した週次予報生成

### プロンプトテンプレート

- **CONTEXT_DAILY.md** - 日次予報用LLMプロンプト（厳密な6段落形式）
- **CONTEXT_WEEKLY.md** - 週次予報用LLMプロンプト（曜日ベースのグループ化）

### データフロー

1. 環境変数からユーザープロファイルを読み込み
2. 住所を緯度経度に変換
3. OpenWeatherMapから予報データを取得
4. 時間帯別にデータを分割（朝/昼/夜）
5. 天気指標を評価し、カテゴリ変換を適用（数値を日本語表現に変換）
6. 服装提案を生成
7. Ollama LLM（モデル: gemma3:4b）にフォーマット済みプロンプトを送信
8. 6段落形式を検証（不正な場合はリトライ）
9. Discordに送信

### 主要な設計パターン

- **適応的リトライ**: 過去50回の失敗率に基づいてリトライ回数を調整
- **フォールバックジオコーディング**: 取得失敗時、逆ジオコーディングで市区町村名を取得して再試行
- **厳密な検証**: 出力は必ず空行で区切られた6段落であること
- **体感温度調整**: ユーザーの寒さ・暑さ耐性でfeels_like値を補正
- **数値カテゴリ化**: LLMに渡すデータは数値ではなく日本語カテゴリ（「暖かい」「蒸し暑い」等）に変換

## LLM出力ルール

プロンプトは厳格なフォーマットを強制:
- 必ず6段落（挨拶、朝、昼、夜、まとめ、結び）
- 番号、ラベル、箇条書き、見出しは禁止
- 気温の数値ではなく体感表現を使用
- 地名は出力しない
- ユーザープロファイル情報は出力に含めない
