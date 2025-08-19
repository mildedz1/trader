from __future__ import annotations

import itertools
from typing import Any, Dict, Optional

from app.http import HttpClient


PERP_BASE_URL = "https://contract.mexc.com/"  # public market data


class MexcPerpDemoClient:
    def __init__(self, initial_balance_usdt: float = 100000.0, base_url: str | None = None, symbol: str = "BTC_USDT") -> None:
        self.base_url = (base_url or PERP_BASE_URL).rstrip("/") + "/"
        self.http = HttpClient(self.base_url)
        self.is_demo: bool = True
        self.symbol = symbol
        self._balance_usdt = float(initial_balance_usdt)
        self._position_qty = 0.0  # in BTC
        self._position_entry = 0.0
        self._orders: Dict[str, Dict[str, Any]] = {}
        self._id_counter = itertools.count(1)

    async def open(self) -> None:
        await self.http.open()

    async def close(self) -> None:
        await self.http.close()

    async def ticker_price(self, symbol: str | None = None) -> float:
        sym = symbol or self.symbol
        # Try contract index; if fails, fallback to spot ticker
        try:
            resp = await self.http.get(f"/api/v1/contract/index/{sym.replace('_','')}")
            data = resp.json()
            if isinstance(data, dict):
                for k in ("indexPrice", "price", "last", "close"):
                    if k in data:
                        return float(data[k])
                if "data" in data and isinstance(data["data"], dict):
                    d = data["data"]
                    for k in ("indexPrice", "price"):
                        if k in d:
                            return float(d[k])
        except Exception:
            pass
        # Spot fallback
        try:
            from app.http import HttpClient as _Http
            spot_sym = sym.replace("_", "")
            async with _Http("https://api.mexc.com/") as h2:
                r2 = await h2.get("api/v3/ticker/price", params={"symbol": spot_sym})
                d2 = r2.json()
                if isinstance(d2, dict) and d2.get("price"):
                    return float(d2["price"])  # type: ignore[arg-type]
        except Exception:
            pass
        return 0.0

    async def account(self) -> Dict[str, Any]:
        # simple account view
        px = await self.ticker_price()
        upnl = (px - self._position_entry) * self._position_qty if self._position_qty != 0 else 0.0
        equity = self._balance_usdt + upnl
        return {
            "asset": "USDT",
            "balance": self._balance_usdt,
            "equity": equity,
            "position": {
                "symbol": self.symbol,
                "qty": self._position_qty,
                "entry": self._position_entry,
                "uPnL": upnl,
            },
        }

    async def create_order(self, params: Dict[str, str]) -> Dict[str, Any]:
        # params: symbol, side (BUY/SELL), type (LIMIT/MARKET), quantity (in BTC), price(optional)
        side = (params.get("side") or "").upper()
        otype = (params.get("type") or "").upper()
        qty = float(str(params.get("quantity") or 0))
        price = params.get("price")
        if otype == "MARKET" or not price:
            fill_price = await self.ticker_price()
        else:
            fill_price = float(str(price))

        # market or cross fill
        executed = qty
        notional = executed * fill_price
        if side == "BUY":
            # increase long position; reduce balance by fee-less notional (isolated simplification)
            self._position_entry = (
                (self._position_entry * self._position_qty) + notional
            ) / max(self._position_qty + executed, 1e-12)
            self._position_qty += executed
        else:
            # reduce long or go short (simplified: allow negative qty)
            self._position_qty -= executed
            if self._position_qty == 0:
                self._position_entry = 0.0

        oid = str(next(self._id_counter))
        order = {
            "symbol": self.symbol,
            "orderId": oid,
            "status": "FILLED",
            "type": otype,
            "side": side,
            "price": f"{fill_price}",
            "executedQty": f"{executed}",
        }
        self._orders[oid] = order
        return order

    async def cancel_order(self, params: Dict[str, str]) -> Dict[str, Any]:
        oid = params.get("orderId")
        if oid and oid in self._orders:
            o = self._orders.pop(oid)
            o["status"] = "CANCELED"
            return o
        return {"code": 1, "msg": "not found"}

    async def demo_report(self) -> Dict[str, Any]:
        acct = await self.account()
        return {
            "perp": True,
            "symbol": self.symbol,
            "equityUSDT": acct.get("equity"),
            "balanceUSDT": acct.get("balance"),
            "position": acct.get("position"),
            "openOrders": list(self._orders.values()),
        }

