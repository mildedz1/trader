from __future__ import annotations

import aiohttp
import asyncio
import hashlib
import hmac
import json
import os
import random
import string
import time
from typing import Any, Dict, List, Optional

from loguru import logger


class LBankNativeSpotClient:
	BASE_URL = "https://api.lbank.info"

	def __init__(self, api_key: str, api_secret: str):
		self.api_key = api_key
		self.api_secret = api_secret.encode()
		self.session: Optional[aiohttp.ClientSession] = None

	async def connect(self) -> None:
		if self.session is None:
			self.session = aiohttp.ClientSession()

	async def close(self) -> None:
		if self.session is not None:
			await self.session.close()
			self.session = None

	async def _timestamp(self) -> str:
		# LBank timestamp endpoint
		async with self.session.get(f"{self.BASE_URL}/v2/timestamp.do") as resp:
			data = await resp.json(content_type=None)
			ts = str(data.get("data") or int(time.time() * 1000))
			return ts

	def _echostr(self, n: int = 16) -> str:
		return ''.join(random.choices(string.ascii_letters + string.digits, k=n))

	def _sign(self, params: Dict[str, Any], timestamp: str, echostr: str) -> str:
		# Canonical string: sorted by key, urlencoded style "key=value&...", append timestamp and echostr
		items = sorted((k, v) for k, v in params.items() if v is not None)
		payload = "&".join(f"{k}={v}" for k, v in items)
		payload += f"&timestamp={timestamp}&echostr={echostr}"
		digest = hmac.new(self.api_secret, payload.encode(), hashlib.sha256).hexdigest()
		return digest

	async def _request(self, path: str, method: str = "GET", params: Optional[Dict[str, Any]] = None, private: bool = False) -> Any:
		assert self.session is not None, "session not initialized"
		url = f"{self.BASE_URL}{path}"
		headers: Dict[str, str] = {"accept": "application/json"}
		params = params or {}
		body = None
		if private:
			ts = await self._timestamp()
			echo = self._echostr()
			signature = self._sign(params, ts, echo)
			headers.update({
				"X-LB-APIKEY": self.api_key,
				"X-LB-SIGN": signature,
				"X-LB-TIMESTAMP": ts,
				"X-LB-ECHOSTR": echo,
				"content-type": "application/json",
			})
			body = json.dumps(params)
		try:
			log_params = {key: params[key] for key in params if 'secret' not in key}
		except Exception:
			log_params = {}
		logger.info(f"LBANK REST {method} {path} params={log_params}")
		if method == "GET":
			async with self.session.get(url, params=params if not private else None, headers=headers) as resp:
				text = await resp.text()
				logger.info(f"LBANK REST RESP {resp.status} {path} {text[:256]}")
				return json.loads(text)
		else:
			async with self.session.post(url, data=body if private else json.dumps(params), headers=headers) as resp:
				text = await resp.text()
				logger.info(f"LBANK REST RESP {resp.status} {path} {text[:256]}")
				return json.loads(text)

	@staticmethod
	def _sym(symbol: str) -> str:
		# LBank uses lowercase with underscore
		return symbol.replace("/", "_").lower()

	# Public endpoints
	async def ping(self) -> Any:
		return await self._request("/v2/supplement/system_ping.do")

	async def ticker_price(self, symbol: str) -> float:
		res = await self._request("/v2/supplement/ticker/price.do", params={"symbol": self._sym(symbol)})
		if isinstance(res, dict) and "data" in res:
			return float(res["data"].get("price") or 0.0)
		return 0.0

	async def book_ticker(self, symbol: str) -> Dict[str, Any]:
		res = await self._request("/v2/supplement/ticker/bookTicker.do", params={"symbol": self._sym(symbol)})
		return res.get("data") if isinstance(res, dict) else {}

	async def trades(self, symbol: str, limit: int = 50) -> Any:
		return await self._request("/v2/supplement/trades.do", params={"symbol": self._sym(symbol), "size": limit})

	async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 300) -> List[List[float]]:
		# Use legacy kline.do with 'type' (e.g., 1min, 5min, 15min, 30min, 1hour)
		type_map = {
			"1m": "1min",
			"3m": "3min",
			"5m": "5min",
			"15m": "15min",
			"30m": "30min",
			"1h": "1hour",
		}
		k_type = type_map.get(timeframe, "5min")
		res = await self._request("/v2/kline.do", params={"symbol": self._sym(symbol), "type": k_type, "size": limit})
		if not isinstance(res, dict) or (str(res.get("result")).lower() == "false"):
			return []
		data = res.get("data") or []
		# LBank kline: [timestamp, open, high, low, close, volume]
		ohlcv: List[List[float]] = []
		for k in data:
			try:
				ohlcv.append([k[0], float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])])
			except Exception:
				continue
		return ohlcv

	# Private Spot Trading (Supplement)
	async def fetch_balance(self) -> Dict[str, Any]:
		res = await self._request("/v2/supplement/user_info_account.do", method="POST", params={}, private=True)
		return res.get("data") or {}

	async def create_order(self, symbol: str, side: str, type_: str, price: Optional[float], amount: float) -> Any:
		params = {
			"symbol": self._sym(symbol),
			"type": side,  # buy/sell
			"price": price if price is not None else 0,
			"amount": amount,
			"externalOrderId": f"bot_{int(time.time()*1000)}",
		}
		res = await self._request("/v2/supplement/create_order.do", method="POST", params=params, private=True)
		if res.get("code") not in (0, "0"):
			msg = res.get("msg") or res.get("message") or str(res)
			raise RuntimeError(f"LBank create_order rejected: {msg}")
		return res

	async def cancel_order(self, symbol: str, order_id: str) -> Any:
		params = {"symbol": self._sym(symbol), "order_id": order_id}
		return await self._request("/v2/supplement/cancel_order.do", method="POST", params=params, private=True)

	async def fetch_open_orders(self, symbol: str) -> List[Dict[str, Any]]:
		params = {"symbol": self._sym(symbol)}
		res = await self._request("/v2/supplement/orders_info_no_deal.do", method="POST", params=params, private=True)
		return res.get("data") or []

	# Helper wrappers for bot
	async def create_market_buy_quote(self, symbol: str, amount_quote: float) -> Any:
		price = await self.ticker_price(symbol)
		if price <= 0:
			raise RuntimeError("No price for market buy")
		amount_base = amount_quote / price
		return await self.create_order(symbol, "buy", "market", price, amount_base)

	async def create_market_sell_base(self, symbol: str, amount_base: float) -> Any:
		return await self.create_order(symbol, "sell", "market", None, amount_base)