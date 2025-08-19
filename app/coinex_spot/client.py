from __future__ import annotations

import json
from typing import Any, Dict

from app.http import HttpClient
from app.signing.coinex import CoinexSigner
from app.time_sync import TimeSynchronizer


BASE_URL = "https://api.coinex.com/"


class CoinexSpotClient:
    def __init__(self, access_id: str, secret_key: str, time_sync: TimeSynchronizer, base_url: str | None = None, window_time_ms: int = 5000) -> None:
        self.signer = CoinexSigner(access_id=access_id, secret_key=secret_key, window_time_ms=window_time_ms)
        self.time_sync = time_sync
        self.base_url = (base_url or BASE_URL).rstrip("/") + "/"
        self.http = HttpClient(self.base_url)

    async def open(self) -> None:
        await self.http.open()

    async def close(self) -> None:
        await self.http.close()

    def _ts(self) -> str:
        return str(self.time_sync.now_ms())

    @staticmethod
    def _norm_symbol(symbol: str) -> str:
        s = symbol.replace("_", "").replace("-", "").replace("/", "").upper()
        return s

    async def normalize_symbol(self, symbol: str) -> str:
        return self._norm_symbol(symbol)

    # Public endpoints
    async def server_time(self) -> Dict[str, Any]:
        resp = await self.http.get("v2/common/svr-time")
        return resp.json()

    async def ticker_price(self, symbol: str) -> Dict[str, Any]:
        market = await self.normalize_symbol(symbol)
        path = f"/v2/market/ticker?market={market}"
        resp = await self.http.get(path.lstrip("/"))
        return resp.json()

    # Private endpoints
    async def user_info_account(self) -> Dict[str, Any]:
        method = "GET"
        path = "/v2/account/balance"
        ts = self._ts()
        headers = self.signer.build_headers(method, path, "", ts)
        resp = await self.http.get(path.lstrip("/"), headers=headers)
        return resp.json()

    async def create_order(self, params: Dict[str, str]) -> Dict[str, Any]:
        market = await self.normalize_symbol(params.get("symbol", ""))
        side = (params.get("side") or "").lower()
        typ = (params.get("type") or "").lower()
        amount = str(params.get("quantity") or params.get("amount") or "0")
        price = params.get("price")
        body: Dict[str, Any] = {
            "market": market,
            "side": "buy" if side == "buy" else "sell",
            "amount": amount,
            "type": "market" if typ == "market" else "limit",
        }
        if price and body["type"] == "limit":
            body["price"] = str(price)
        payload = json.dumps(body, separators=(",", ":"))
        method = "POST"
        path = "/v2/spot/order"
        ts = self._ts()
        headers = self.signer.build_headers(method, path, payload, ts)
        resp = await self.http.post(path.lstrip("/"), json=body, headers=headers)
        return resp.json()

    async def cancel_order(self, params: Dict[str, str]) -> Dict[str, Any]:
        market = await self.normalize_symbol(params.get("symbol", ""))
        order_id = params.get("orderId")
        body = {"market": market, "order_id": order_id}
        payload = json.dumps(body, separators=(",", ":"))
        method = "POST"
        path = "/v2/spot/cancel-order"
        ts = self._ts()
        headers = self.signer.build_headers(method, path, payload, ts)
        resp = await self.http.post(path.lstrip("/"), json=body, headers=headers)
        return resp.json()

