# Weather Forecast

AIを活用した天気予報アプリケーション。パーソナライズされた日次・週次の天気予報と服装提案を生成し、Discordに送信します。

## 機能

- 日次天気予報（朝・昼・夜の時間帯別）
- 週次天気予報（曜日ベースのグループ化）
- ユーザーの寒さ・暑さ耐性に基づく体感温度補正
- 天気に応じた服装提案
- Discord Webhook経由での通知

## 必要条件

- Python 3.x
- ローカルOllamaサーバー（gemma3:4bモデル）

## インストール

```bash
pip install requests python-dotenv
```

## 設定

uvを実行するディレクトリに `.env` ファイルを作成し、以下の環境変数を設定してください:

```env
OPENWEATHER_API_KEY=your_api_key
DISCORD_WEBHOOK_URL=your_webhook_url
OLLAMA_URL=http://localhost:11434
USER_ADDRESS=東京都渋谷区
USER_COLD_TOLERANCE=普通
USER_HEAT_TOLERANCE=普通
```

| 変数 | 説明 |
|------|------|
| `OPENWEATHER_API_KEY` | OpenWeatherMap APIキー |
| `DISCORD_WEBHOOK_URL` | Discord Webhook URL |
| `OLLAMA_URL` | Ollamaサーバーのエンドポイント |
| `USER_ADDRESS` | 予報対象の住所 |
| `USER_COLD_TOLERANCE` | 寒さ耐性: `弱い` または `普通` |
| `USER_HEAT_TOLERANCE` | 暑さ耐性: `弱い` または `普通` |

## 使い方

```bash
# 日次予報
python forecast_daily.py

# 週次予報
python forecast_weekly.py
```

## ファイル構成

```
weather-forecast/
├── weather_lib.py      # 共通ライブラリ
├── forecast_daily.py   # 日次予報スクリプト
├── forecast_weekly.py  # 週次予報スクリプト
├── CONTEXT_DAILY.md    # 日次予報用プロンプトテンプレート
├── CONTEXT_WEEKLY.md   # 週次予報用プロンプトテンプレート
└── .env                # 環境変数設定ファイル
```

## ライセンス

MIT License
