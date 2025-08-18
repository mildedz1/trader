from __future__ import annotations

from typing import Any, Dict, List

import ccxt.async_support as ccxt  # type: ignore

from .base import Exchange


class LBankFutures(Exchange):
	def __init__(self, api_key: str = "", api_secret: str = ""):
		self.exchange = ccxt.lbank({
			"apiKey": api_key,
			"secret": api_secret,
			"enableRateLimit": True,
			"options": {"defaultType": "swap"},
		})

	async def connect(self) -> None:
		await self.exchange.load_markets()

	async def close(self) -> None:
		try:
			await self.exchange.close()
		except Exception:
			pass

	def _resolve_symbol(self, symbol: str) -> str:
		markets = getattr(self.exchange, "markets", {}) or {}
		if symbol in markets:
			return symbol
		base, quote = symbol.split("/")
		for s, m in markets.items():
			if m.get("type") == "swap" and m.get("base") == base and m.get("quote") == quote:
				return s
		cand = f"{base}/{quote}:USDT"
		if cand in markets:
			return cand
		return symbol

	async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 300) -> List[List[float]]:
		sym = self._resolve_symbol(symbol)
		# Some venues don't provide swap OHLCV reliably; fallback to spot symbol
		try:
			return await self.exchange.fetch_ohlcv(sym, timeframe=timeframe, limit=limit)
		except Exception:
			spot = sym.split(":")[0]
			return await self.exchange.fetch_ohlcv(spot, timeframe=timeframe, limit=limit)

	async def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
		sym = self._resolve_symbol(symbol)
		return await self.exchange.fetch_ticker(sym)

	async def fetch_balance(self) -> Dict[str, Any]:
		return await self.exchange.fetch_balance()

	async def create_market_buy_order(self, symbol: str, amount_quote: float) -> Dict[str, Any]:
		sym = self._resolve_symbol(symbol)
		t = await self.fetch_ticker(sym)
		price = float(t.get("last") or t.get("close") or 0.0)
		amount_base = amount_quote / max(price, 1e-8)
		amount_base = float(self.exchange.amount_to_precision(sym, amount_base))
		return await self.exchange.create_order(sym, type="market", side="buy", amount=amount_base, price=price)

	async def create_market_sell_order(self, symbol: str, amount_base: float) -> Dict[str, Any]:
		sym = self._resolve_symbol(symbol)
		amount_base = float(self.exchange.amount_to_precision(sym, amount_base))
		return await self.exchange.create_order(sym, type="market", side="sell", amount=amount_base)

	async def set_leverage(self, symbol: str, leverage: int) -> None:
		sym = self._resolve_symbol(symbol)
		if hasattr(self.exchange, "setLeverage"):
			await self.exchange.setLeverage(leverage, sym)  # type: ignore[attr-defined]