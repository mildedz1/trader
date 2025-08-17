from __future__ import annotations

from typing import Any, Dict, List, Tuple

import ccxt.async_support as ccxt  # type: ignore

from .base import ExchangeAdapter


class CcxtLBankAdapter(ExchangeAdapter):
	def __init__(self, api_key: str | None, api_secret: str | None):
		self.api_key = api_key or ""
		self.api_secret = api_secret or ""
		self.exchange = ccxt.lbank({
			"apiKey": self.api_key,
			"secret": self.api_secret,
			"enableRateLimit": True,
		})

	async def connect(self) -> None:
		# Warn about key permissions; we cannot check withdrawal perms via API reliably
		# Validate we can load markets and fetch a public ticker
		await self.exchange.load_markets()

	async def close(self) -> None:  # type: ignore[override]
		try:
			await self.exchange.close()
		except Exception:
			pass

	async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 300) -> List[List[float]]:
		return await self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

	async def fetch_balance(self) -> Dict[str, Any]:
		return await self.exchange.fetch_balance()

	async def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
		return await self.exchange.fetch_ticker(symbol)

	async def create_market_buy_order(self, symbol: str, amount_quote: float) -> Dict[str, Any]:
		# Convert quote amount to base amount using ticker price
		ticker = await self.fetch_ticker(symbol)
		price = float(ticker.get("last") or ticker.get("close"))
		if price <= 0:
			raise ValueError("Invalid ticker price for market buy")
		amount_base = amount_quote / price
		amount_base = float(self.exchange.amount_to_precision(symbol, amount_base))
		return await self.exchange.create_order(symbol, type="market", side="buy", amount=amount_base)

	async def create_market_sell_order(self, symbol: str, amount_base: float) -> Dict[str, Any]:
		amount_base = float(self.exchange.amount_to_precision(symbol, amount_base))
		return await self.exchange.create_order(symbol, type="market", side="sell", amount=amount_base)

	async def get_price_precision(self, symbol: str) -> Tuple[int, int]:
		market = self.exchange.market(symbol)
		amount_decimals = market.get("precision", {}).get("amount", 8)
		price_decimals = market.get("precision", {}).get("price", 8)
		return amount_decimals, price_decimals