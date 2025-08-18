# Telegram LBank Spot Trader Worker (BTC/USDT)

Production-ready, Dockerized Telegram-controlled worker that trades BTC/USDT on LBank Spot using a simple EMA/RSI strategy. Supports demo (paper) and live modes.

## Features
- Async LBank via ccxt (async)
- Strategy: Long-only, EMA trend filter (EMA50 > EMA200), RSI(14) cross-up through 30 to enter, exit when RSI ≥ 70 or EMA50 ≤ EMA200
- Telegram bot (aiogram v3): /start, /status, /pause, /resume, /config, /logs
- Daily loss limit with auto-pause
- Demo mode (paper trading) or live mode (real orders)
- No withdrawals supported (and never implemented). Use API keys with Trade+Read only; disable withdrawals at exchange level.
- Dockerized, non-root, healthcheck, compose

## Quick start

1. Prepare `.env` (or export env vars) with your tokens/keys. IMPORTANT: Create LBank API keys with Trade+Read only and Withdrawals disabled at the exchange.

2. Build and run:
```bash
docker compose up -d --build
```

3. Interact via Telegram with the bot. Only allowed chat IDs can control the worker.

### Update config at runtime
Use `/config {json}` to persist overrides. Example:
```text
/config {"EMA_FAST": 34, "EMA_SLOW": 144, "RSI_ENTRY": 32}
```
Restart the container to fully apply persisted changes.

## Environment Variables

| Variable | Default | Description |
|---|---:|---|
| TELEGRAM_TOKEN | (required) | Telegram bot token |
| ALLOWED_CHAT_IDS | (required) | Comma-separated list of Telegram chat IDs allowed to control the bot |
| EXCHANGE_ID | lbank | Exchange id for ccxt |
| LBANK_API_KEY | (required for live) | LBank API key (Trade+Read only; withdrawals disabled) |
| LBANK_API_SECRET | (required for live) | LBank API secret |
| SYMBOL | BTC/USDT | Trading pair |
| TIMEFRAME | 1h | OHLCV timeframe |
| EMA_FAST | 50 | Fast EMA period |
| EMA_SLOW | 200 | Slow EMA period |
| RSI_PERIOD | 14 | RSI period |
| RSI_ENTRY | 30 | RSI cross-up entry threshold |
| RSI_EXIT | 70 | RSI exit threshold |
| TICK_INTERVAL_SEC | 15 | Tick interval for worker loop |
| RISK_POSITION_MODE | percent_of_balance | percent_of_balance or fixed_amount |
| RISK_POSITION_SIZE | 0.01 | If percent_of_balance: fraction of quote balance; if fixed_amount: quote amount in USDT |
| MAX_DAILY_LOSS_PCT | 3 | Max daily loss percent (relative to reset equity). Trading pauses when hit |
| RESET_HOUR_UTC | 0 | Hour in UTC to reset daily loss metrics |
| MODE | demo | demo (paper) or live |
| CONFIG_PATH | /data/config.json | Path to persisted config override file |
| LOG_PATH | /data/logs/worker.log | Path to log file |
| HEARTBEAT_PATH | /data/heartbeat | Path to heartbeat file used by healthcheck |

## Healthcheck
Container health is based on a heartbeat file updated by the worker each tick. If the heartbeat is stale, the container is marked unhealthy.

## Safety
- There is NO withdrawal logic in this application.
- App warns on startup: Use keys with Trade+Read only and Withdrawals disabled.
- The app will attempt to validate API connectivity. It cannot reliably verify key-level withdrawal permission; configure keys correctly and keep withdrawal disabled at the exchange.

## Testing
Run unit tests locally:
```bash
pip install -r requirements.txt --break-system-packages
~/.local/bin/pytest -q
```

## Notes
- By default, the service runs in demo mode and will simulate orders using the paper adapter while still fetching public OHLCV from LBank via ccxt.
- To enable live trading, set `MODE=live` and provide `LBANK_API_KEY` and `LBANK_API_SECRET` (Trade+Read only; withdrawals disabled).

## Fast update (dev)

Use the override to bind-mount source and avoid rebuilds:

```bash
docker compose -f docker-compose.yml -f docker-compose.override.yml up -d
# After editing Python files, just restart container to reload process
docker compose restart trader_worker
```

For dependency changes (requirements.txt) or base image updates, rebuild:
```bash
docker compose up -d --build
```