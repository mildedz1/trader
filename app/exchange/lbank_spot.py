from __future__ import annotations

from typing import Any, Dict, List

import ccxt.async_support as ccxt  # type: ignore

from .base import Exchange


class LBankSpot(Exchange):
	def __init__(self, api_key: str = "", api_secret: str = ""):
		self.exchange = ccxt.lbank({
			"apiKey": api_key,
			"secret": api_secret,
			"enableRateLimit": True,
			"options": {"defaultType": "spot"},
		})

	async def connect(self) -> None:
		await self.exchange.load_markets()

	async def close(self) -> None:
		try:
			await self.exchange.close()
		except Exception:
			pass

	async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 300) -> List[List[float]]:
		return await self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

	async def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
		return await self.exchange.fetch_ticker(symbol)

	async def fetch_balance(self) -> Dict[str, Any]:
		return await self.exchange.fetch_balance()

	async def create_market_buy_order(self, symbol: str, amount_quote: float) -> Dict[str, Any]:
		t = await self.fetch_ticker(symbol)
		price = float(t.get("last") or t.get("close") or 0.0)
		amount_base = amount_quote / max(price, 1e-8)
		amount_base = float(self.exchange.amount_to_precision(symbol, amount_base))
		return await self.exchange.create_order(symbol, type="market", side="buy", amount=amount_base, price=price)

	async def create_market_sell_order(self, symbol: str, amount_base: float) -> Dict[str, Any]:
		amount_base = float(self.exchange.amount_to_precision(symbol, amount_base))
		return await self.exchange.create_order(symbol, type="market", side="sell", amount=amount_base)