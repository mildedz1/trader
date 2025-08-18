from __future__ import annotations

from typing import Any, Dict, List, Tuple
from loguru import logger

import ccxt.async_support as ccxt  # type: ignore
from .base import ExchangeAdapter


class CcxtLBankFuturesAdapter(ExchangeAdapter):
	def __init__(self, api_key: str | None, api_secret: str | None):
		self.api_key = api_key or ""
		self.api_secret = api_secret or ""
		self.exchange = ccxt.lbank({
			"apiKey": self.api_key,
			"secret": self.api_secret,
			"enableRateLimit": True,
			"options": {"defaultType": "swap"},
		})
		self._spot_ccxt = ccxt.lbank({
			"apiKey": self.api_key,
			"secret": self.api_secret,
			"enableRateLimit": True,
			"options": {"defaultType": "spot"},
		})

	async def connect(self) -> None:
		try:
			await self.exchange.load_markets(reload=False)
		except Exception:
			await self.exchange.load_markets()
		try:
			await self._spot_ccxt.load_markets(reload=False)
		except Exception:
			await self._spot_ccxt.load_markets()

	async def close(self) -> None:
		try:
			await self.exchange.close()
		except Exception:
			pass
		try:
			await self._spot_ccxt.close()
		except Exception:
			pass

	def _resolve_symbol(self, symbol: str) -> str:
		try:
			markets = getattr(self.exchange, "markets", {}) or {}
			if symbol in markets and markets[symbol].get("type") == "swap":
				return symbol
			base, quote = symbol.split("/")
			for s, m in markets.items():
				if m.get("type") == "swap" and m.get("base") == base and m.get("quote") == quote:
					return s
			u = symbol.upper()
			if u in markets and markets[u].get("type") == "swap":
				return u
			candidate = f"{base}/{quote}:USDT"
			if candidate in markets and markets[candidate].get("type") == "swap":
				return candidate
		except Exception:
			pass
		logger.debug(f"LBankFutures _resolve_symbol fallback -> {symbol}")
		return symbol

	def _spot_symbol(self, symbol: str) -> str:
		return symbol.split(":")[0]

	async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 300) -> List[List[float]]:
		spot_sym = self._spot_symbol(symbol)
		try:
			return await self._spot_ccxt.fetch_ohlcv(spot_sym, timeframe=timeframe, limit=limit)
		except Exception:
			return []

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
		price = None
		if side.lower() == "buy":
			ticker = await self.exchange.fetch_ticker(sym)
			price = float(ticker.get("last") or ticker.get("close") or 0.0)
			if price <= 0:
				raise ValueError("Invalid ticker price for market buy")
			return await self.exchange.create_order(sym, type="market", side=side, amount=amount_base, price=price, params=params)
		return await self.exchange.create_order(sym, type="market", side=side, amount=amount_base, params=params)

	async def create_market_buy_order(self, symbol: str, amount_quote: float) -> Dict[str, Any]:
		sym = self._resolve_symbol(symbol)
		ticker = await self.exchange.fetch_ticker(sym)
		price = float(ticker.get("last") or ticker.get("close") or 0.0)
		if price <= 0:
			raise ValueError("Invalid ticker price for market buy")
		amount_base = amount_quote / price
		amount_base = float(self.exchange.amount_to_precision(sym, amount_base))
		return await self.exchange.create_order(sym, type="market", side="buy", amount=amount_base, price=price)

	async def create_market_sell_order(self, symbol: str, amount_base: float) -> Dict[str, Any]:
		sym = self._resolve_symbol(symbol)
		amount_base = float(self.exchange.amount_to_precision(sym, amount_base))
		return await self.create_market_order(sym, "sell", amount_base)

	async def get_price_precision(self, symbol: str) -> Tuple[int, int]:
		sym = self._resolve_symbol(symbol)
		market = self.exchange.market(sym)
		amount_decimals = market.get("precision", {}).get("amount", 8)
		price_decimals = market.get("precision", {}).get("price", 8)
		return amount_decimals, price_decimals

	def get_market_rules(self, symbol: str) -> Dict[str, float]:
		sym = self._resolve_symbol(symbol)
		market = self.exchange.market(sym)
		limits = market.get("limits", {}) or {}
		precision = market.get("precision", {}) or {}
		min_cost = float((limits.get("cost") or {}).get("min") or 0.0)
		min_amount = float((limits.get("amount") or {}).get("min") or 0.0)
		price_decimals = int(precision.get("price", 8))
		amount_decimals = int(precision.get("amount", 8))
		return {
			"min_cost": min_cost,
			"min_amount": min_amount,
			"price_decimals": float(price_decimals),
			"amount_decimals": float(amount_decimals),
		}

	def round_amount(self, symbol: str, amount: float) -> float:
		sym = self._resolve_symbol(symbol)
		return float(self.exchange.amount_to_precision(sym, amount))

	def round_price(self, symbol: str, price: float) -> float:
		sym = self._resolve_symbol(symbol)
		return float(self.exchange.price_to_precision(sym, price))