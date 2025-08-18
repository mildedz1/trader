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

	def _sign_contract(self, params: Dict[str, Any], timestamp: str, echostr: str) -> str:
		items = sorted((k, v) for k, v in params.items() if v is not None and k != "sign")
		payload = "&".join(f"{k}={v}" for k, v in items)
		payload += f"&timestamp={timestamp}&echostr={echostr}"
		return hmac.new(self.api_secret, payload.encode(), hashlib.sha256).hexdigest()

	async def _request(self, path: str, method: str = "GET", params: Optional[Dict[str, Any]] = None, private: bool = False) -> Any:
		assert self.session is not None, "session not initialized"
		url = f"{self.BASE_URL}{path}"
		headers: Dict[str, str] = {
			"accept": "application/json, text/plain, */*",
			"user-agent": "Mozilla/5.0 (X11; Linux x86_64) TelegramWorker/1.0 aiohttp",
		}
		params = params or {}
		body = None
		if private:
			# Contract private headers & signing
			# timestamp must be server time
			try:
				ser = await self._request("/cfd/openApi/v1/pub/getTime")
				ts = str(ser.get("data"))
			except Exception:
				ts = ""
			echo = self._echostr(32)
			sign = self._sign_contract(params, ts, echo)
			params = dict(params)
			params["sign"] = sign
			headers.update({
				"content-type": "application/json",
				"timestamp": ts,
				"signature_method": "HmacSHA256",
				"echostr": echo,
			})
			body = json.dumps(params)
		logger.info(f"LBANK FUTURES REST {method} {path} params={{{k:params[k] for k in params if 'secret' not in k}}}")
		if method == "GET":
			async with self.session.get(url, params=params if not private else None, headers=headers) as resp:
				text = await resp.text()
				if "text/html" in (resp.headers.get("content-type") or "") and "Cloudflare" in text:
					logger.warning(f"LBANK FUTURES RESP {resp.status} {path} Cloudflare page")
					return {"code": resp.status, "msg": "Cloudflare page", "data": None}
				logger.info(f"LBANK FUTURES RESP {resp.status} {path} {text[:256]}")
				return json.loads(text)
		else:
			async with self.session.post(url, data=body if private else json.dumps(params), headers=headers) as resp:
				text = await resp.text()
				if "text/html" in (resp.headers.get("content-type") or "") and "Cloudflare" in text:
					logger.warning(f"LBANK FUTURES RESP {resp.status} {path} Cloudflare page")
					return {"code": resp.status, "msg": "Cloudflare page", "data": None}
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

	# Private endpoints
	async def account_balance(self, asset: str = "USDT", product_group: str = "SwapU") -> Dict[str, Any]:
		payload = {
			"api_key": self.api_key,
			"productGroup": product_group,
			"asset": asset,
		}
		return await self._request("/cfd/openApi/v1/prv/account", method="POST", params=payload, private=True)


class LBankNativeFuturesAdapter:
	def __init__(self, api_key: str | None, api_secret: str | None):
		self.client = LBankNativeFuturesClient(api_key or "", api_secret or "")

	async def connect(self) -> None:
		await self.client.connect()

	async def close(self) -> None:
		await self.client.close()

	# TODO: implement methods compatible with ExchangeAdapter for futures