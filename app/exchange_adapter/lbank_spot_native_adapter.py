from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .base import ExchangeAdapter
from .lbank_native import LBankNativeSpotClient
import ccxt.async_support as ccxt  # type: ignore


class LBankNativeSpotAdapter(ExchangeAdapter):
	def __init__(self, api_key: str | None, api_secret: str | None):
		self.client = LBankNativeSpotClient(api_key or "", api_secret or "")
		self._ccxt_spot = ccxt.lbank({
			"apiKey": api_key or "",
			"secret": api_secret or "",
			"enableRateLimit": True,
			"options": {"defaultType": "spot"},
		})

	async def connect(self) -> None:
		await self.client.connect()
		try:
			await self._ccxt_spot.load_markets(reload=False)
		except Exception:
			await self._ccxt_spot.load_markets()

	async def close(self) -> None:
		await self.client.close()
		try:
			await self._ccxt_spot.close()
		except Exception:
			pass

	def _symbol(self, symbol: str) -> str:
		return symbol

	async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 300) -> List[List[float]]:
		data = await self.client.fetch_ohlcv(symbol, timeframe, limit)
		if data:
			return data
		try:
			return await self._ccxt_spot.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
		except Exception:
			return []

	async def fetch_balance(self) -> Dict[str, Any]:
		# Normalize to {"free": {asset: float}, "total": {asset: float}}
		raw = await self.client.fetch_balance()
		free: Dict[str, float] = {}
		total: Dict[str, float] = {}
		if isinstance(raw, dict):
			if "data" in raw:
				raw = raw["data"]
			can = raw.get("can_use") or raw.get("free") or {}
			freeze = raw.get("freeze") or {}
			asset = raw.get("asset") or {}
			for k, v in can.items():
				try:
					free[k] = float(v)
				except Exception:
					pass
			for k, v in asset.items():
				try:
					total[k] = float(v)
				except Exception:
					# fallback total = free + freeze
					fv = float(can.get(k, 0.0)) + float(freeze.get(k, 0.0))
					total[k] = fv
		return {"free": free, "total": total}

	async def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
		price = await self.client.ticker_price(symbol)
		return {"symbol": symbol, "last": price, "close": price}

	async def fetch_open_orders(self, symbol: str) -> List[Dict[str, Any]]:
		orders = await self.client.fetch_open_orders(symbol)
		return orders or []

	async def create_market_buy_order(self, symbol: str, amount_quote: float) -> Dict[str, Any]:
		return await self.client.create_market_buy_quote(symbol, amount_quote)

	async def create_market_sell_order(self, symbol: str, amount_base: float) -> Dict[str, Any]:
		return await self.client.create_market_sell_base(symbol, amount_base)

	async def get_price_precision(self, symbol: str) -> Tuple[int, int]:
		# LBank REST does not expose precision easily via supplement; fall back to common defaults
		return 8, 8

	def get_market_rules(self, symbol: str) -> Dict[str, float]:
		# Not available from supplement easily; return zeros to defer enforcement to exchange
		return {"min_cost": 0.0, "min_amount": 0.0, "price_decimals": 8.0, "amount_decimals": 8.0}

	def round_amount(self, symbol: str, amount: float) -> float:
		return float(f"{amount:.8f}")

	def round_price(self, symbol: str, price: float) -> float:
		return float(f"{price:.8f}")