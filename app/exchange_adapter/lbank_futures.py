from __future__ import annotations

from typing import Any, Dict, List, Tuple

import ccxt.async_support as ccxt  # type: ignore


class CcxtLBankFuturesAdapter:
	def __init__(self, api_key: str | None, api_secret: str | None):
		self.api_key = api_key or ""
		self.api_secret = api_secret or ""
		self.exchange = ccxt.lbank({
			"apiKey": self.api_key,
			"secret": self.api_secret,
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
		# find matching swap market symbol
		try:
			markets = getattr(self.exchange, "markets", {}) or {}
			if symbol in markets and markets[symbol].get("type") == "swap":
				return symbol
			base, quote = symbol.split("/")
			for s, m in markets.items():
				if m.get("type") == "swap" and m.get("base") == base and m.get("quote") == quote:
					return s
			# fallback to upper
			u = symbol.upper()
			if u in markets and markets[u].get("type") == "swap":
				return u
		except Exception:
			pass
		return symbol

	async def set_leverage(self, symbol: str, leverage: int) -> None:
		sym = self._resolve_symbol(symbol)
		try:
			await self.exchange.setLeverage(leverage, sym)
		except Exception:
			pass

	async def set_position_mode(self, symbol: str, mode: str) -> None:
		sym = self._resolve_symbol(symbol)
		try:
			await self.exchange.setMarginMode(mode, sym)
		except Exception:
			pass

	async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 300) -> List[List[float]]:
		sym = self._resolve_symbol(symbol)
		return await self.exchange.fetch_ohlcv(sym, timeframe=timeframe, limit=limit)

	async def fetch_balance(self) -> Dict[str, Any]:
		return await self.exchange.fetch_balance()

	async def fetch_positions(self, symbol: str | None = None) -> List[Dict[str, Any]]:
		try:
			if symbol:
				sym = self._resolve_symbol(symbol)
				return await self.exchange.fetchPositions([sym])
			return await self.exchange.fetchPositions()
		except Exception:
			return []

	async def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
		sym = self._resolve_symbol(symbol)
		return await self.exchange.fetch_ticker(sym)

	async def create_market_order(self, symbol: str, side: str, amount_base: float, reduce_only: bool = False) -> Dict[str, Any]:
		sym = self._resolve_symbol(symbol)
		params: Dict[str, Any] = {}
		if reduce_only:
			params["reduceOnly"] = True
		return await self.exchange.create_order(sym, type="market", side=side, amount=amount_base, params=params)