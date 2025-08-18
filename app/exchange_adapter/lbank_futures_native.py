from __future__ import annotations

import aiohttp
import hashlib
import hmac
import json
import random
import string
from typing import Any, Dict, List, Optional

from loguru import logger


class LBankNativeFuturesClient:
	BASE_URL = "https://lbkperp.lbank.com"

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

	def _echostr(self, n: int = 16) -> str:
		return ''.join(random.choices(string.ascii_letters + string.digits, k=n))

	def _sign(self, path: str, params: Dict[str, Any], timestamp: str, echostr: str) -> str:
		# Placeholder; actual contract signing may differ from spot supplement
		items = sorted((k, v) for k, v in params.items() if v is not None)
		payload = "&".join(f"{k}={v}" for k, v in items)
		payload += f"&timestamp={timestamp}&echostr={echostr}"
		return hmac.new(self.api_secret, payload.encode(), hashlib.sha256).hexdigest()

	async def _request(self, path: str, method: str = "GET", params: Optional[Dict[str, Any]] = None, private: bool = False) -> Any:
		assert self.session is not None, "session not initialized"
		url = f"{self.BASE_URL}{path}"
		headers: Dict[str, str] = {"accept": "application/json"}
		params = params or {}
		body = None
		if private:
			# TODO: implement correct signing for contract private
			ts = params.get("timestamp") or ""
			echo = params.get("echostr") or self._echostr()
			signature = self._sign(path, params, ts, echo)
			headers.update({
				"X-LB-APIKEY": self.api_key,
				"X-LB-SIGN": signature,
				"X-LB-TIMESTAMP": ts,
				"X-LB-ECHOSTR": echo,
				"content-type": "application/json",
			})
			body = json.dumps(params)
		logger.info(f"LBANK FUTURES REST {method} {path} params={{{k:params[k] for k in params if 'secret' not in k}}}")
		if method == "GET":
			async with self.session.get(url, params=params if not private else None, headers=headers) as resp:
				text = await resp.text()
				logger.info(f"LBANK FUTURES RESP {resp.status} {path} {text[:256]}")
				return json.loads(text)
		else:
			async with self.session.post(url, data=body if private else json.dumps(params), headers=headers) as resp:
				text = await resp.text()
				logger.info(f"LBANK FUTURES RESP {resp.status} {path} {text[:256]}")
				return json.loads(text)

	# Public endpoints
	async def server_time(self) -> int:
		res = await self._request("/cfd/openApi/v1/pub/getTime")
		return int(res.get("data") or 0)

	async def instruments(self) -> Any:
		return await self._request("/cfd/openApi/v1/pub/instrument")

	async def market_data(self, symbol: str) -> Any:
		return await self._request("/cfd/openApi/v1/pub/marketData", params={"symbol": symbol})

	async def market_orderbook(self, symbol: str, depth: int = 10) -> Any:
		return await self._request("/cfd/openApi/v1/pub/marketOrder", params={"symbol": symbol, "depth": depth})


class LBankNativeFuturesAdapter:
	def __init__(self, api_key: str | None, api_secret: str | None):
		self.client = LBankNativeFuturesClient(api_key or "", api_secret or "")

	async def connect(self) -> None:
		await self.client.connect()

	async def close(self) -> None:
		await self.client.close()

	# TODO: implement methods compatible with ExchangeAdapter for futures