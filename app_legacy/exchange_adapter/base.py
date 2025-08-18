from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


class ExchangeAdapter:
	async def connect(self) -> None:  # validate credentials and connectivity
		raise NotImplementedError

	async def close(self) -> None:
		return None

	async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 300) -> List[List[float]]:
		raise NotImplementedError

	async def fetch_balance(self) -> Dict[str, Any]:
		raise NotImplementedError

	async def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
		raise NotImplementedError

	async def fetch_open_orders(self, symbol: str) -> List[Dict[str, Any]]:
		raise NotImplementedError

	async def create_market_buy_order(self, symbol: str, amount_quote: float) -> Dict[str, Any]:
		raise NotImplementedError

	async def create_market_sell_order(self, symbol: str, amount_base: float) -> Dict[str, Any]:
		raise NotImplementedError

	async def get_price_precision(self, symbol: str) -> Tuple[int, int]:
		"""Return (base_precision, quote_precision) decimals for amount and price rounding."""
		raise NotImplementedError