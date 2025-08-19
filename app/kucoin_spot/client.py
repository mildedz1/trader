from __future__ import annotations

import json
import time
from typing import Any, Dict

from app.http import HttpClient
from app.signing.kucoin import KucoinSigner
from app.time_sync import TimeSynchronizer


BASE_URL = "https://openapi-sandbox.kucoin.com/"  # KuCoin Sandbox


class KucoinSpotClient:
    def __init__(self, api_key: str, secret_key: str, passphrase: str, time_sync: TimeSynchronizer, base_url: str | None = None) -> None:
        self.signer = KucoinSigner(api_key=api_key, secret_key=secret_key, passphrase=passphrase)
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
        s = symbol.replace("_", "-").replace("/", "-").upper()
        if "-" not in s and s.endswith("USDT"):
            s = s[:-4] + "-USDT"
        return s

    async def normalize_symbol(self, symbol: str) -> str:
        return self._norm_symbol(symbol)

    async def ticker_price(self, symbol: str) -> Dict[str, Any]:
        sym = await self.normalize_symbol(symbol)
        path = f"/api/v1/market/orderbook/level1?symbol={sym}"
        headers = self.signer.build_headers(self._ts(), "GET", path)
        resp = await self.http.get(path.lstrip("/"), headers=headers)
        return resp.json()

    async def user_info_account(self) -> Dict[str, Any]:
        path = "/api/v1/accounts"
        headers = self.signer.build_headers(self._ts(), "GET", path)
        resp = await self.http.get(path.lstrip("/"), headers=headers)
        data = resp.json()
        # normalize
        bals = []
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            for it in data["data"]:
                bals.append({"asset": it.get("currency"), "free": it.get("available"), "locked": it.get("holds")})
        return {"balances": bals}

    async def create_order(self, params: Dict[str, str]) -> Dict[str, Any]:
        sym = await self.normalize_symbol(params.get("symbol", ""))
        side = (params.get("side") or "").lower()
        ord_type = (params.get("type") or "").lower()
        qty = str(params.get("quantity") or params.get("amount") or "0")
        px = params.get("price")
        body: Dict[str, Any] = {
            "clientOid": str(time.time_ns()),
            "side": "buy" if side == "buy" else "sell",
            "symbol": sym,
            "type": "market" if ord_type == "market" else "limit",
        }
        if body["type"] == "limit":
            body["price"] = px
            body["size"] = qty
        else:
            body["size"] = qty
        path = "/api/v1/orders"
        payload = json.dumps(body, separators=(",", ":"))
        headers = self.signer.build_headers(self._ts(), "POST", path, body=payload)
        resp = await self.http.post(path.lstrip("/"), json=body, headers=headers)
        return resp.json()

    async def cancel_order(self, params: Dict[str, str]) -> Dict[str, Any]:
        oid = params.get("orderId")
        path = f"/api/v1/orders/{oid}"
        headers = self.signer.build_headers(self._ts(), "DELETE", path)
        resp = await self.http.delete(path.lstrip("/"), headers=headers)
        return resp.json()

