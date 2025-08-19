from __future__ import annotations

import urllib.parse
from typing import Any, Dict, Optional

from app.http import HttpClient
from app.signing.mexc import MexcSpotSigner
from app.time_sync import TimeSynchronizer


SPOT_BASE_URL = "https://api.mexc.com/"


class MexcSpotClient:
    def __init__(self, api_key: str, secret_key: str, time_sync: TimeSynchronizer, base_url: str | None = None) -> None:
        self.api_key = api_key
        self.signer = MexcSpotSigner(secret_key=secret_key)
        self.time_sync = time_sync
        self.base_url = (base_url or SPOT_BASE_URL).rstrip("/") + "/"
        # Default headers; API key is sent via X-MEXC-APIKEY
        self.http = HttpClient(self.base_url, headers={"X-MEXC-APIKEY": self.api_key})
        # lowercase -> canonical symbol (uppercase)
        self._pair_map: dict[str, str] = {}

    async def open(self) -> None:
        await self.http.open()

    async def close(self) -> None:
        await self.http.close()

    # Public
    async def system_ping(self) -> Dict[str, Any]:
        resp = await self.http.get("api/v3/ping")
        return resp.json() or {"ok": True}

    async def server_time(self) -> Dict[str, Any]:
        resp = await self.http.get("api/v3/time")
        return resp.json()

    async def exchange_info(self) -> Dict[str, Any]:
        resp = await self.http.get("api/v3/exchangeInfo")
        return resp.json()

    async def currency_pairs(self) -> dict[str, str]:
        if self._pair_map:
            return self._pair_map
        info = await self.exchange_info()
        mapping: dict[str, str] = {}
        symbols = []
        if isinstance(info, dict):
            symbols = info.get("symbols") or info.get("data") or []
        for s in symbols:
            sym = s.get("symbol")
            if isinstance(sym, str):
                mapping[sym.lower()] = sym
        self._pair_map = mapping
        return self._pair_map

    async def normalize_symbol(self, symbol: str) -> str:
        pairs = await self.currency_pairs()
        sl = symbol.replace("/", "").replace("_", "").replace("-", "").lower()
        # try direct upper
        if sl in pairs:
            return pairs[sl]
        # fallback common: uppercase of input without separators
        return symbol.replace("/", "").replace("_", "").replace("-", "").upper()

    async def ticker_price(self, symbol: str) -> Dict[str, Any]:
        try:
            sym = await self.normalize_symbol(symbol)
        except Exception:
            sym = symbol
        resp = await self.http.get("api/v3/ticker/price", params={"symbol": sym})
        return resp.json()

    # Private endpoints
    async def _auth_params(self, extra: Dict[str, Any] | None = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {"timestamp": str(self.time_sync.now_ms())}
        if extra:
            params.update(extra)
        return params

    def _signed_query(self, params: Dict[str, Any]) -> str:
        # Build query string and sign
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)
        signature = self.signer.sign(query)
        if query:
            return f"{query}&signature={signature}"
        return f"signature={signature}"

    async def user_info_account(self) -> Dict[str, Any]:
        params = await self._auth_params({"recvWindow": "5000"})
        q = self._signed_query(params)
        # MEXC expects signature in query string and API key header
        resp = await self.http.get(f"api/v3/account?{q}")
        return resp.json()

    async def create_order(self, params: Dict[str, str]) -> Dict[str, Any]:
        # Normalize symbol and map engine params to MEXC
        data: Dict[str, Any] = {}
        if "symbol" in params and params["symbol"]:
            try:
                data["symbol"] = await self.normalize_symbol(params["symbol"])  # type: ignore[index]
            except Exception:
                data["symbol"] = params["symbol"]
        # type mapping: expects LIMIT or MARKET
        order_type = params.get("type")
        if order_type in ("buy", "sell"):
            # shouldn't happen here, but map to LIMIT by default
            data["type"] = "LIMIT"
        else:
            data["type"] = "MARKET" if str(order_type).lower().startswith("buy_") or str(order_type).lower().startswith("sell_") or order_type == "market" else "LIMIT"
        # side
        side = params.get("side")
        if side:
            data["side"] = str(side).upper()
        else:
            # If engine passes type like buy/sell, infer from earlier logic
            t = params.get("type", "")
            data["side"] = "BUY" if "buy" in str(t).lower() else "SELL"

        qty = params.get("amount") or params.get("quantity")
        if qty is not None:
            data["quantity"] = str(qty)
        price = params.get("price")
        if price is not None and data.get("type") == "LIMIT":
            data["price"] = str(price)
            data["timeInForce"] = "GTC"

        # clientOrderId if provided
        coid = params.get("custom_id") or params.get("clientOrderId")
        if coid:
            data["newClientOrderId"] = str(coid)

        # Build signed form body or query
        auth = await self._auth_params(data)
        q = self._signed_query(auth)
        # Send as application/x-www-form-urlencoded as widely supported
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        resp = await self.http.post("api/v3/order", data=q, headers=headers)
        return resp.json()

    async def cancel_order(self, params: Dict[str, str]) -> Dict[str, Any]:
        # DELETE /api/v3/order?symbol=BTCUSDT&orderId=12345
        data: Dict[str, Any] = {}
        if "symbol" in params and params["symbol"]:
            try:
                data["symbol"] = await self.normalize_symbol(params["symbol"])  # type: ignore[index]
            except Exception:
                data["symbol"] = params["symbol"]
        if "orderId" in params:
            data["orderId"] = params["orderId"]
        elif "origClientOrderId" in params:
            data["origClientOrderId"] = params["origClientOrderId"]
        auth = await self._auth_params(data)
        q = self._signed_query(auth)
        resp = await self.http.delete(f"api/v3/order?{q}")
        return resp.json()

