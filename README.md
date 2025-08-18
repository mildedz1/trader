## LBank Telegram Trader Bot (Python 3.11)

Production-ready, modular Telegram trading bot for LBank Spot (V2) and Perp/Contract (v1) APIs. Implements official LBank headers, signature (sorted params -> MD5 uppercase -> HMAC-SHA256/RSA), time sync, and strict rate limits.

Stack: aiogram v3, httpx (async), SQLAlchemy + SQLite, APScheduler, structlog, pydantic Settings, Fernet encryption at rest.

Quick start

1) Copy .env.example to .env and fill values
2) Build and run

```bash
cp .env.example .env
docker compose up --build
```