from __future__ import annotations

import json
import os
from typing import List, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator


class Settings(BaseModel):
	# Telegram
	telegram_token: str = Field(alias="TELEGRAM_TOKEN")
	allowed_chat_ids: List[int] = Field(alias="ALLOWED_CHAT_IDS")

	# Exchange/keys
	exchange_id: str = Field(default="lbank", alias="EXCHANGE_ID")
	lbank_api_key: Optional[str] = Field(default=None, alias="LBANK_API_KEY")
	lbank_api_secret: Optional[str] = Field(default=None, alias="LBANK_API_SECRET")
	lbank_use_native_spot: bool = Field(default=True, alias="LBANK_USE_NATIVE_SPOT")
	lbank_use_native_futures: bool = Field(default=False, alias="LBANK_USE_NATIVE_FUTURES")

	# Trade mode
	trade_mode: str = Field(default="futures", alias="TRADE_MODE")  # spot | futures

	# Spot trading (macd_zero_trend)
	symbol: str = Field(default="ETH/USDT", alias="SYMBOL")
	timeframe: str = Field(default="30m", alias="TIMEFRAME")
	ema_fast: int = Field(default=50, alias="EMA_FAST")
	ema_slow: int = Field(default=200, alias="EMA_SLOW")
	macd_fast: int = Field(default=12, alias="MACD_FAST")
	macd_slow: int = Field(default=26, alias="MACD_SLOW")
	macd_signal: int = Field(default=9, alias="MACD_SIGNAL")
	rsi_confirm: bool = Field(default=False, alias="RSI_CONFIRM")
	rsi_confirm_level: float = Field(default=45.0, alias="RSI_CONFIRM_LEVEL")

	# Futures trading (futures_scalp_st)
	futures_symbol: str = Field(default="ETH/USDT", alias="FUTURES_SYMBOL")
	futures_timeframe: str = Field(default="5m", alias="FUTURES_TIMEFRAME")
	futures_leverage: int = Field(default=5, alias="FUTURES_LEVERAGE")
	futures_position_mode: str = Field(default="isolated", alias="FUTURES_POSITION_MODE")  # isolated|cross
	futures_max_positions: int = Field(default=1, alias="FUTURES_MAX_POSITIONS")
	futures_allow_short: bool = Field(default=True, alias="FUTURES_ALLOW_SHORT")
	futures_testnet: bool = Field(default=False, alias="FUTURES_TESTNET")
	st_supertrend_atr_period: int = Field(default=10, alias="ST_ATR_PERIOD")
	st_supertrend_atr_mult: float = Field(default=2.5, alias="ST_ATR_MULT")
	# For futures scalp, override default EMAs faster
	ema_fast: int = Field(default=20, alias="EMA_FAST")
	ema_slow: int = Field(default=50, alias="EMA_SLOW")
	sl_atr_mult: float = Field(default=1.0, alias="SL_ATR_MULT")
	tp_rr: float = Field(default=1.2, alias="TP_RR")
	trail_enable: bool = Field(default=True, alias="TRAIL_ENABLE")
	trail_atr_mult: float = Field(default=0.8, alias="TRAIL_ATR_MULT")
	cooldown_candles_after_exit: int = Field(default=1, alias="COOLDOWN_CANDLES")
	max_trades_per_day: int = Field(default=50, alias="MAX_TRADES_PER_DAY")
	min_seconds_between_trades: int = Field(default=30, alias="MIN_SECONDS_BETWEEN_TRADES")
	use_full_balance: bool = Field(default=True, alias="USE_FULL_BALANCE")

	# Risk & loop
	tick_interval_sec: float = Field(default=15.0, alias="TICK_INTERVAL_SEC")
	risk_position_mode: str = Field(default="fixed_amount", alias="RISK_POSITION_MODE")
	risk_position_size: float = Field(default=1.0, alias="RISK_POSITION_SIZE")  # USDT for spot
	max_daily_loss_pct: float = Field(default=3.0, alias="MAX_DAILY_LOSS_PCT")
	reset_hour_utc: int = Field(default=0, alias="RESET_HOUR_UTC")

	# Mode (live-only)
	mode: str = Field(default="live", alias="MODE")

	# Persistence & logs
	config_path: str = Field(default="/data/config.json", alias="CONFIG_PATH")
	log_path: str = Field(default="/data/logs/worker.log", alias="LOG_PATH")
	heartbeat_path: str = Field(default="/data/heartbeat", alias="HEARTBEAT_PATH")

	@field_validator("allowed_chat_ids", mode="before")
	@classmethod
	def parse_chat_ids(cls, v: str | list[int]):
		if isinstance(v, list):
			return v
		if not isinstance(v, str) or not v.strip():
			raise ValueError("ALLOWED_CHAT_IDS is required and must be comma-separated integers")
		return [int(x.strip()) for x in v.split(",") if x.strip()]

	@field_validator("risk_position_mode")
	@classmethod
	def validate_risk_mode(cls, v: str):
		allowed = {"fixed_amount"}
		if v not in allowed:
			raise ValueError(f"RISK_POSITION_MODE must be one of {allowed} for live-only mode")
		return v

	@field_validator("mode")
	@classmethod
	def validate_mode(cls, v: str):
		if v != "live":
			raise ValueError("Only live mode is supported (no demo/paper)")
		return v

	@field_validator("trade_mode")
	@classmethod
	def validate_trade_mode(cls, v: str):
		allowed = {"spot", "futures"}
		if v not in allowed:
			raise ValueError(f"TRADE_MODE must be one of {allowed}")
		return v

	@classmethod
	def load(cls) -> "Settings":
		data = {k: v for k, v in os.environ.items()}
		# Allow persisted overrides if present
		config_path = data.get("CONFIG_PATH", "/data/config.json")
		if os.path.exists(config_path):
			try:
				with open(config_path, "r", encoding="utf-8") as f:
					persisted = json.load(f)
				# persisted values override env
				data.update({k: str(v) if not isinstance(v, str) else v for k, v in persisted.items()})
			except Exception:
				pass
		try:
			return cls.model_validate(data)
		except ValidationError as e:
			raise SystemExit(f"Configuration error: {e}") from e

	def persist_overrides(self, overrides: dict) -> None:
		# Update only known fields
		allowed_keys = {f.alias for f in self.model_fields.values()}
		filtered = {k: v for k, v in overrides.items() if k in allowed_keys}
		os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
		try:
			if os.path.exists(self.config_path):
				with open(self.config_path, "r", encoding="utf-8") as f:
					existing = json.load(f)
			else:
				existing = {}
			existing.update(filtered)
			with open(self.config_path, "w", encoding="utf-8") as f:
				json.dump(existing, f, indent=2)
		except Exception as exc:  # noqa: BLE001
			raise RuntimeError(f"Failed to persist config: {exc}") from exc