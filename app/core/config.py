from __future__ import annotations

import os
from typing import List

from pydantic import BaseModel, Field, field_validator


class Settings(BaseModel):
	telegram_token: str = Field(alias="TELEGRAM_TOKEN")
	allowed_chat_ids: List[int] = Field(alias="ALLOWED_CHAT_IDS")
	symbol: str = Field(default="ETH/USDT", alias="SYMBOL")
	timeframe: str = Field(default="30m", alias="TIMEFRAME")
	mode: str = Field(default="live", alias="MODE")

	@field_validator("allowed_chat_ids", mode="before")
	@classmethod
	def parse_chat_ids(cls, v: str | list[int]):
		if isinstance(v, list):
			return v
		return [int(x.strip()) for x in str(v).split(",") if str(x).strip()]