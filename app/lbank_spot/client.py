from __future__ import annotations

import asyncio
import secrets
from typing import Any, Dict, Optional

from app.http import HttpClient
from app.signing import SpotSigner, random_echostr
from app.time_sync import TimeSynchronizer
from app.logging import logger


SPOT_BASE_URLS = ["https://api.lbkex.com/", "https://api.lbank.info/"]


class LBankSpotClient:
    def __init__(self, api_key: str, secret_key: str, time_sync: TimeSynchronizer, base_url: str | None = None) -> None:
        self.api_key = api_key
        self.signer = SpotSigner(secret_key=secret_key)
        self.time_sync = time_sync
        self.base_url = (base_url or SPOT_BASE_URLS[0]).rstrip("/") + "/"
        self.http = HttpClient(self.base_url, headers={"X-Api-Key": self.api_key})
        self._pairs: set[str] = set()

    async def open(self) -> None:
        await self.http.open()

    async def close(self) -> None:
        await self.http.close()

    async def _security_params(self) -> Dict[str, str]:
        ts = self.time_sync.now_ms()
        return {
            "api_key": self.api_key,
            "timestamp": str(ts),
            "signature_method": "HmacSHA256",
            "echostr": random_echostr(32),
        }

    # Public
    async def system_ping(self) -> Dict[str, Any]:
        resp = await self.http.get("v2/supplement/system_ping.do")
        return resp.json()

    async def server_time(self) -> Dict[str, Any]:
        resp = await self.http.get("v2/timestamp.do")
        return resp.json()

    async def ticker_price(self, symbol: str) -> Dict[str, Any]:
        # LBank expects lowercase symbols like btc_usdt on V2 supplement endpoints
        resp = await self.http.get("v2/supplement/ticker/price.do", params={"symbol": symbol.lower()})
        return resp.json()

    async def currency_pairs(self) -> set[str]:
        if self._pairs:
            return self._pairs
        resp = await self.http.get("v2/currencyPairs.do")
        data = resp.json()
        pairs: set[str] = set()
        if isinstance(data, dict) and "data" in data:
            for s in data["data"]:
                pairs.add(str(s).lower())
        elif isinstance(data, list):
            for s in data:
                pairs.add(str(s).lower())
        self._pairs = pairs
        return self._pairs

    async def normalize_symbol(self, symbol: str) -> str:
        pairs = await self.currency_pairs()
        sl = symbol.lower().replace("/", "_")
        if sl in pairs:
            return sl
        raise ValueError(f"Unsupported symbol on LBank spot: {symbol}")

    # Private
    async def create_order_test(self, params: Dict[str, str]) -> Dict[str, Any]:
        base = await self._security_params()
        data = {**params, **base}
        headers, signed = self.signer.build_headers_and_signature(data)
        resp = await self.http.post("v2/supplement/create_order_test.do", data=signed, headers=headers)
        return resp.json()

    async def create_order(self, params: Dict[str, str]) -> Dict[str, Any]:
        base = await self._security_params()
        data = {**params, **base}
        if "symbol" in data:
            data["symbol"] = await self.normalize_symbol(str(data["symbol"]))
        headers, signed = self.signer.build_headers_and_signature(data)
        resp = await self.http.post("v2/supplement/create_order.do", data=signed, headers=headers)
        return resp.json()

    async def cancel_order(self, params: Dict[str, str]) -> Dict[str, Any]:
        base = await self._security_params()
        data = {**params, **base}
        headers, signed = self.signer.build_headers_and_signature(data)
        resp = await self.http.post("v2/supplement/cancel_order.do", data=signed, headers=headers)
        return resp.json()

    async def cancel_order_by_symbol(self, params: Dict[str, str]) -> Dict[str, Any]:
        base = await self._security_params()
        data = {**params, **base}
        headers, signed = self.signer.build_headers_and_signature(data)
        resp = await self.http.post("v2/supplement/cancel_order_by_symbol.do", data=signed, headers=headers)
        return resp.json()

    async def orders_info(self, params: Dict[str, str]) -> Dict[str, Any]:
        base = await self._security_params()
        data = {**params, **base}
        headers, signed = self.signer.build_headers_and_signature(data)
        resp = await self.http.post("v2/supplement/orders_info.do", data=signed, headers=headers)
        return resp.json()

    async def user_info_account(self) -> Dict[str, Any]:
        base = await self._security_params()
        headers, signed = self.signer.build_headers_and_signature(base)
        resp = await self.http.post("v2/supplement/user_info_account.do", data=signed, headers=headers)
        return resp.json()