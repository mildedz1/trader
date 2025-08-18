from __future__ import annotations

from typing import Any, Dict, List, Tuple


class Exchange:
	async def connect(self) -> None:
		raise NotImplementedError

	async def close(self) -> None:
		return None

	async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 300) -> List[List[float]]:
		raise NotImplementedError

	async def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
		raise NotImplementedError

	async def fetch_balance(self) -> Dict[str, Any]:
		raise NotImplementedError

	async def create_market_buy_order(self, symbol: str, amount_quote: float) -> Dict[str, Any]:
		raise NotImplementedError

	async def create_market_sell_order(self, symbol: str, amount_base: float) -> Dict[str, Any]:
		raise NotImplementedError

	async def set_leverage(self, symbol: str, leverage: int) -> None:
		return None

	async def set_margin_mode(self, symbol: str, mode: str) -> None:
		return None

	def round_amount(self, symbol: str, amount: float) -> float:
		return amount

	def get_market_rules(self, symbol: str) -> Dict[str, float]:
		return {}