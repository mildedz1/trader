from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

from .base import ExchangeAdapter


class PaperAdapter(ExchangeAdapter):
	def __init__(self, starting_quote_balance: float = 10_000.0, starting_base_balance: float = 0.0):
		self.quote = starting_quote_balance
		self.base = starting_base_balance
		self._last_price: float = 0.0

	async def connect(self) -> None:
		return None

	async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 300) -> List[List[float]]:  # pragma: no cover - delegated to ccxt in live
		raise NotImplementedError("Paper adapter does not provide OHLCV; fetch via live adapter or strategy fetcher")

	async def fetch_balance(self) -> Dict[str, Any]:
		return {
			"free": {"USDT": self.quote, "BTC": self.base},
			"total": {"USDT": self.quote, "BTC": self.base},
		}

	async def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
		return {"symbol": symbol, "last": self._last_price or 0.0}

	async def create_market_buy_order(self, symbol: str, amount_quote: float) -> Dict[str, Any]:
		price = self._last_price
		if price <= 0:
			raise ValueError("Price not set for paper trading")
		amount_base = amount_quote / price
		amount_base = round(amount_base, 8)
		if amount_quote > self.quote:
			raise ValueError("Insufficient quote balance")
		self.quote -= amount_quote
		self.base += amount_base
		return {"type": "market", "side": "buy", "amount": amount_base, "price": price, "ts": int(time.time() * 1000)}

	async def create_market_sell_order(self, symbol: str, amount_base: float) -> Dict[str, Any]:
		price = self._last_price
		if price <= 0:
			raise ValueError("Price not set for paper trading")
		amount_base = round(amount_base, 8)
		if amount_base > self.base:
			raise ValueError("Insufficient base balance")
		self.base -= amount_base
		self.quote += amount_base * price
		return {"type": "market", "side": "sell", "amount": amount_base, "price": price, "ts": int(time.time() * 1000)}

	async def get_price_precision(self, symbol: str) -> Tuple[int, int]:
		return 8, 2

	def set_last_price(self, price: float) -> None:
		self._last_price = float(price)