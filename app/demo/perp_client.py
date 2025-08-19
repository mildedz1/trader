from __future__ import annotations

import itertools
from typing import Any, Dict

from app.http import HttpClient


PERP_PRICE_URL = "https://api.coinex.com/"  # use spot price as mark for demo


class DemoPerpClient:
    def __init__(self, initial_balance_usdt: float = 100000.0, symbol: str = "BTC_USDT", leverage: float = 10.0) -> None:
        self.http = HttpClient(PERP_PRICE_URL)
        self.is_demo: bool = True
        self.symbol = symbol
        self.leverage = max(1.0, float(leverage))
        self._balance_usdt = float(initial_balance_usdt)
        self._position_qty = 0.0  # in base asset
        self._entry = 0.0
        self._orders: Dict[str, Dict[str, Any]] = {}
        self._id = itertools.count(1)

    async def open(self) -> None:
        await self.http.open()

    async def close(self) -> None:
        await self.http.close()

    async def _mark_price(self) -> float:
        sym = self.symbol.replace("_", "")
        try:
            resp = await self.http.get("v2/market/ticker", params={"market": sym})
            data = resp.json()
            d = data.get("data") or data
            for key in ("last", "price", "close"):
                if key in d:
                    return float(d[key])
            if isinstance(d, list) and d:
                o = d[0]
                for key in ("last", "price", "close"):
                    if key in o:
                        return float(o[key])
        except Exception:
            pass
        return 0.0

    async def ticker_price(self, symbol: str | None = None) -> float:
        return await self._mark_price()

    async def account(self) -> Dict[str, Any]:
        px = await self._mark_price()
        upnl = (px - self._entry) * self._position_qty * self.leverage if self._position_qty != 0 else 0.0
        equity = self._balance_usdt + upnl
        return {"equity": equity, "balance": self._balance_usdt, "symbol": self.symbol, "position": {"qty": self._position_qty, "entry": self._entry, "uPnL": upnl, "lev": self.leverage}}

    async def create_order(self, params: Dict[str, str]) -> Dict[str, Any]:
        side = (params.get("side") or "").upper()
        typ = (params.get("type") or "").upper()
        qty = float(str(params.get("quantity") or 0))
        px = await self._mark_price()
        executed = qty
        notional = executed * px / max(self.leverage, 1e-12)
        if side == "BUY":
            self._entry = ((self._entry * self._position_qty) + executed * px) / max(self._position_qty + executed, 1e-12)
            self._position_qty += executed
            self._balance_usdt -= notional
        else:
            self._position_qty -= executed
            if self._position_qty == 0:
                self._entry = 0.0
            self._balance_usdt += notional
        oid = str(next(self._id))
        order = {"orderId": oid, "status": "FILLED", "type": typ, "side": side, "price": f"{px}", "executedQty": f"{executed}", "symbol": self.symbol}
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
        return {"perp": True, **acct, "openOrders": list(self._orders.values())}

