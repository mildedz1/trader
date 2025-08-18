from __future__ import annotations

import json
import os
from typing import List, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator


class Settings(BaseModel):
	# Telegram
	telegram_token: str = Field(alias="TELEGRAM_TOKEN")
	allowed_chat_ids: List[int] = Field(alias="ALLOWED_CHAT_IDS")

	# Trade mode
	trade_mode: str = Field(default="spot", alias="TRADE_MODE")  # spot|futures

	# Spot
	symbol: str = Field(default="ETH/USDT", alias="SYMBOL")
	timeframe: str = Field(default="30m", alias="TIMEFRAME")

	# Futures
	futures_symbol: str = Field(default="ETH/USDT:USDT", alias="FUTURES_SYMBOL")
	futures_timeframe: str = Field(default="5m", alias="FUTURES_TIMEFRAME")
	futures_leverage: int = Field(default=5, alias="FUTURES_LEVERAGE")
	use_full_balance: bool = Field(default=True, alias="USE_FULL_BALANCE")
	futures_margin_usdt: Optional[float] = Field(default=None, alias="FUTURES_MARGIN_USDT")

	# Loop & risk
	tick_interval_sec: float = Field(default=15.0, alias="TICK_INTERVAL_SEC")

	# Mode
	mode: str = Field(default="live", alias="MODE")

	# Persist
	config_path: str = Field(default="/data/config.json", alias="CONFIG_PATH")

	@field_validator("allowed_chat_ids", mode="before")
	@classmethod
	def parse_chat_ids(cls, v: str | list[int]):
		if isinstance(v, list):
			return v
		return [int(x.strip()) for x in str(v).split(",") if str(x).strip()]

	@field_validator("trade_mode")
	@classmethod
	def validate_trade_mode(cls, v: str):
		v = (v or "").strip().lower()
		return v if v in {"spot", "futures"} else "spot"

	@classmethod
	def load(cls) -> "Settings":
		data = {k: v for k, v in os.environ.items()}
		cfg = data.get("CONFIG_PATH", "/data/config.json")
		if os.path.exists(cfg):
			try:
				with open(cfg, "r", encoding="utf-8") as f:
					persisted = json.load(f)
				data.update({k: str(v) if not isinstance(v, str) else v for k, v in persisted.items()})
			except Exception:
				pass
		try:
			return cls.model_validate(data)
		except ValidationError as e:
			raise SystemExit(f"Configuration error: {e}")

	def persist_overrides(self, overrides: dict) -> None:
		allowed = {f.alias for f in self.model_fields.values()}
		filtered = {k: v for k, v in overrides.items() if k in allowed}
		os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
		try:
			existing = {}
			if os.path.exists(self.config_path):
				with open(self.config_path, "r", encoding="utf-8") as f:
					existing = json.load(f)
			existing.update(filtered)
			with open(self.config_path, "w", encoding="utf-8") as f:
				json.dump(existing, f, indent=2)
		except Exception as exc:
			raise RuntimeError(f"Failed to persist config: {exc}") from exc