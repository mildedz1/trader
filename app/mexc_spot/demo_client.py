from __future__ import annotations

import itertools
from typing import Any, Dict, Optional

from app.http import HttpClient


SPOT_BASE_URL = "https://api.mexc.com/"


class MexcSpotDemoClient:
    def __init__(self, initial_balances: Optional[Dict[str, float]] = None, base_url: str | None = None) -> None:
        self.base_url = (base_url or SPOT_BASE_URL).rstrip("/") + "/"
        self.http = HttpClient(self.base_url)
        # balances tracked as {asset: {free: float, locked: float}}
        self._balances: Dict[str, Dict[str, float]] = {}
        init = initial_balances or {"USDT": 100000.0}
        for asset, amt in init.items():
            self._balances[asset.upper()] = {"free": float(amt), "locked": 0.0}
        self._pair_map: dict[str, str] = {}
        self._orders: Dict[str, Dict[str, Any]] = {}
        self._id_counter = itertools.count(1)

    async def open(self) -> None:
        await self.http.open()

    async def close(self) -> None:
        await self.http.close()

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
        s = symbol.replace("_", "").replace("-", "").replace("/", "").lower()
        return pairs.get(s, s.upper())

    async def ticker_price(self, symbol: str) -> Dict[str, Any]:
        sym = await self.normalize_symbol(symbol)
        resp = await self.http.get("api/v3/ticker/price", params={"symbol": sym})
        return resp.json()

    async def user_info_account(self) -> Dict[str, Any]:
        balances = [
            {"asset": asset, "free": f"{info['free']}", "locked": f"{info['locked']}"}
            for asset, info in sorted(self._balances.items())
        ]
        return {"balances": balances}

    async def create_order(self, params: Dict[str, str]) -> Dict[str, Any]:
        # Simulate order placement and fills against latest price
        sym = await self.normalize_symbol(params.get("symbol", ""))
        side = (params.get("side") or "").upper()
        otype = (params.get("type") or "").upper()
        qty = float(str(params.get("quantity") or params.get("amount") or 0))
        price_param = params.get("price")
        last_price_obj = await self.ticker_price(sym)
        last_price = float(str(last_price_obj.get("price") or last_price_obj.get("last") or 0))
        price = float(str(price_param)) if price_param is not None else last_price

        base, quote = self._split_symbol(sym)
        order_id = str(next(self._id_counter))

        status = "NEW"
        filled_qty = 0.0

        def ensure_asset(a: str) -> None:
            self._balances.setdefault(a, {"free": 0.0, "locked": 0.0})

        ensure_asset(base)
        ensure_asset(quote)

        # Market: fill immediately at last price
        fill_now = False
        if otype == "MARKET":
            fill_now = True
        elif otype == "LIMIT":
            # Fill if price crosses last price
            if side == "BUY" and price >= last_price:
                fill_now = True
            if side == "SELL" and price <= last_price:
                fill_now = True

        if fill_now:
            notional = qty * price
            if side == "BUY":
                # Check quote balance
                if self._balances[quote]["free"] + 1e-12 < notional:
                    return {"code": 700001, "msg": "Insufficient balance in demo"}
                self._balances[quote]["free"] -= notional
                self._balances[base]["free"] += qty
            else:  # SELL
                if self._balances[base]["free"] + 1e-12 < qty:
                    return {"code": 700001, "msg": "Insufficient balance in demo"}
                self._balances[base]["free"] -= qty
                self._balances[quote]["free"] += notional
            status = "FILLED"
            filled_qty = qty

        order = {
            "symbol": sym,
            "orderId": order_id,
            "clientOrderId": params.get("newClientOrderId") or params.get("clientOrderId"),
            "price": f"{price}",
            "origQty": f"{qty}",
            "executedQty": f"{filled_qty}",
            "status": status,
            "type": otype,
            "side": side,
        }
        if status != "FILLED":
            self._orders[order_id] = order
        return order

    async def cancel_order(self, params: Dict[str, str]) -> Dict[str, Any]:
        oid = params.get("orderId")
        if oid and oid in self._orders:
            order = self._orders.pop(oid)
            order["status"] = "CANCELED"
            return order
        return {"code": 700002, "msg": "Order not found in demo"}

    @staticmethod
    def _split_symbol(sym: str) -> tuple[str, str]:
        s = sym.upper()
        # naive split on common quote assets
        for q in ("USDT", "USDC", "BTC", "ETH"):
            if s.endswith(q):
                return s[: -len(q)], q
        # fallback
        return s, "USDT"

