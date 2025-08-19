from __future__ import annotations

import json
import time
from typing import Any, Dict

from app.http import HttpClient
from app.signing.okx import OkxSigner
from app.time_sync import TimeSynchronizer


BASE_URL = "https://www.okx.com/"


class OkxSpotClient:
    def __init__(self, api_key: str, secret_key: str, passphrase: str, time_sync: TimeSynchronizer, base_url: str | None = None, simulated: bool = False) -> None:
        self.signer = OkxSigner(api_key=api_key, secret_key=secret_key, passphrase=passphrase)
        self.time_sync = time_sync
        self.base_url = (base_url or BASE_URL).rstrip("/") + "/"
        self.simulated = simulated
        self.http = HttpClient(self.base_url)
        self._pair_map: dict[str, str] = {}

    async def open(self) -> None:
        await self.http.open()

    async def close(self) -> None:
        await self.http.close()

    def _ts(self) -> str:
        return str(self.time_sync.now_ms() / 1000.0)

    @staticmethod
    def _norm_symbol(symbol: str) -> str:
        s = symbol.replace("_", "-").replace("/", "-").upper()
        # if no dash, insert before last 4 chars assuming USDT
        if "-" not in s and s.endswith("USDT"):
            s = s[:-4] + "-USDT"
        return s

    async def normalize_symbol(self, symbol: str) -> str:
        return self._norm_symbol(symbol)

    async def ticker_price(self, symbol: str) -> Dict[str, Any]:
        instId = await self.normalize_symbol(symbol)
        path = f"/api/v5/market/ticker?instId={instId}"
        ts = self._ts()
        headers = self.signer.build_headers(ts, "GET", path, simulated=self.simulated)
        resp = await self.http.get(path.lstrip("/"), headers=headers)
        data = resp.json()
        # data: { code:"0", data:[{"last":"..."}], msg:""}
        return data

    async def user_info_account(self) -> Dict[str, Any]:
        # Try asset balances first
        ts = self._ts()
        path = "/api/v5/asset/balances"
        headers = self.signer.build_headers(ts, "GET", path, simulated=self.simulated)
        resp = await self.http.get(path.lstrip("/"), headers=headers)
        data = resp.json()
        if isinstance(data, dict) and data.get("code") == "0":
            # normalize to balances list
            items = data.get("data") or []
            bals = []
            for it in items:
                bals.append({
                    "asset": it.get("ccy"),
                    "free": it.get("availBal"),
                    "locked": it.get("frozenBal") or "0",
                })
            return {"balances": bals}
        # fallback: account/balance
        path2 = "/api/v5/account/balance"
        headers2 = self.signer.build_headers(ts, "GET", path2, simulated=self.simulated)
        resp2 = await self.http.get(path2.lstrip("/"), headers=headers2)
        d2 = resp2.json()
        return d2

    async def create_order(self, params: Dict[str, str]) -> Dict[str, Any]:
        instId = await self.normalize_symbol(params.get("symbol", ""))
        side = (params.get("side") or "").lower()
        ord_type = (params.get("type") or "").lower()
        qty = str(params.get("quantity") or params.get("amount") or "0")
        px = params.get("price")
        cl_id = params.get("clientOrderId") or params.get("clOrdId")

        body: Dict[str, Any] = {
            "instId": instId,
            "tdMode": "cash",
            "side": "buy" if side == "buy" else "sell",
            "ordType": "market" if ord_type == "market" else "limit",
            "sz": qty,
        }
        if px and body["ordType"] == "limit":
            body["px"] = str(px)
        if cl_id:
            body["clOrdId"] = str(cl_id)[:32]

        path = "/api/v5/trade/order"
        ts = self._ts()
        payload = json.dumps(body, separators=(",", ":"))
        headers = self.signer.build_headers(ts, "POST", path, body=payload, simulated=self.simulated)
        resp = await self.http.post(path.lstrip("/"), json=body, headers=headers)
        return resp.json()

    async def cancel_order(self, params: Dict[str, str]) -> Dict[str, Any]:
        instId = await self.normalize_symbol(params.get("symbol", ""))
        ordId = params.get("orderId")
        clOrdId = params.get("clientOrderId")
        body: Dict[str, Any] = {"instId": instId}
        if ordId:
            body["ordId"] = ordId
        if clOrdId:
            body["clOrdId"] = clOrdId
        path = "/api/v5/trade/cancel-order"
        ts = self._ts()
        payload = json.dumps(body, separators=(",", ":"))
        headers = self.signer.build_headers(ts, "POST", path, body=payload, simulated=self.simulated)
        resp = await self.http.post(path.lstrip("/"), json=body, headers=headers)
        return resp.json()

