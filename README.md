## MEXC Telegram Trader Bot (Python 3.11)

Production-ready, modular Telegram trading bot for CoinEx Spot API (v2). Implements HMAC-SHA256 signing per docs.

Stack: aiogram v3, httpx (async), SQLAlchemy + SQLite, APScheduler, structlog, pydantic Settings, Fernet encryption at rest.

Quick start

1) Copy .env.example to .env and fill values
2) Build and run

```bash
cp .env.example .env
docker compose up --build
```

Environment variables (.env):

- COINEX_ACCESS_ID
- COINEX_SECRET_KEY
- FERNET_KEY
- TELEGRAM_BOT_TOKEN
- ADMIN_TELEGRAM_USER_IDS

Optional (only if you keep sample LBank Perp module enabled):

- LBANK_PERP_API_KEY
- LBANK_PERP_SECRET_KEY