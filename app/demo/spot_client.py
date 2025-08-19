from __future__ import annotations

import itertools
from typing import Any, Dict, Optional

from app.http import HttpClient


SPOT_BASE_URL = "https://api.coinex.com/"


class DemoSpotClient:
    def __init__(self, initial_balances: Optional[Dict[str, float]] = None, slippage_bps: int = 5, enable_partial_fills: bool = True, base_url: str | None = None) -> None:
        self.base_url = (base_url or SPOT_BASE_URL).rstrip("/") + "/"
        self.http = HttpClient(self.base_url)
        self.is_demo: bool = True
        self._pair_map: dict[str, str] = {}
        self._orders: Dict[str, Dict[str, Any]] = {}
        self._id_counter = itertools.count(1)
        self._balances: Dict[str, Dict[str, float]] = {}
        init = initial_balances or {"USDT": 100000.0}
        for asset, amt in init.items():
            self._balances[asset.upper()] = {"free": float(amt), "locked": 0.0}
        self._slippage_bps = max(0, int(slippage_bps))
        self._partial_fills = bool(enable_partial_fills)
        # inventory avg cost for unrealized pnl (by base asset)
        self._inventory: Dict[str, Dict[str, float]] = {}
        self._realized_pnl_usdt: float = 0.0
        self._trade_log: list[Dict[str, Any]] = []

    async def open(self) -> None:
        await self.http.open()

    async def close(self) -> None:
        await self.http.close()

    @staticmethod
    def _norm_symbol(symbol: str) -> str:
        return symbol.replace("_", "").replace("-", "").replace("/", "").upper()

    async def normalize_symbol(self, symbol: str) -> str:
        return self._norm_symbol(symbol)

    async def ticker_price(self, symbol: str) -> Dict[str, Any]:
        market = await self.normalize_symbol(symbol)
        resp = await self.http.get("v2/market/ticker", params={"market": market})
        return resp.json()

    async def _mark_price(self, symbol: str) -> float:
        data = await self.ticker_price(symbol)
        # Try common shapes
        if isinstance(data, dict):
            d = data.get("data") or data
            # direct fields
            for key in ("last", "price", "lastPrice", "close"):
                if key in d:
                    try:
                        return float(d[key])
                    except Exception:
                        pass
            # nested list under data
            if isinstance(d, list) and d:
                obj = d[0]
                for key in ("last", "price", "close"):
                    if key in obj:
                        try:
                            return float(obj[key])
                        except Exception:
                            pass
        return 0.0

    async def user_info_account(self) -> Dict[str, Any]:
        balances = [
            {"asset": a, "free": f"{info['free']}", "locked": f"{info['locked']}"}
            for a, info in sorted(self._balances.items())
        ]
        return {"balances": balances}

    async def create_order(self, params: Dict[str, str]) -> Dict[str, Any]:
        sym = await self.normalize_symbol(params.get("symbol", ""))
        side = (params.get("side") or "").upper()
        typ = (params.get("type") or "").upper()
        qty = float(str(params.get("quantity") or params.get("amount") or 0))
        price_param = params.get("price")
        last_price = await self._mark_price(sym)
        price = float(str(price_param)) if price_param is not None else last_price

        base, quote = self._split_symbol(sym)
        self._ensure_asset(base)
        self._ensure_asset(quote)

        order_id = str(next(self._id_counter))
        status = "NEW"
        executed = 0.0
        fill_price = price

        # Fill logic
        fill_fraction = 0.0
        if typ == "MARKET":
            fill_fraction = 1.0
            slip = self._slippage_bps / 10000.0
            fill_price = last_price * (1 + slip) if side == "BUY" else last_price * (1 - slip)
        else:  # LIMIT
            if side == "BUY" and last_price >= price:
                over = (last_price - price) / max(price, 1e-12)
                fill_fraction = 1.0 if not self._partial_fills else max(0.3, min(1.0, 0.3 + over * 5))
            if side == "SELL" and last_price <= price:
                under = (price - last_price) / max(price, 1e-12)
                fill_fraction = 1.0 if not self._partial_fills else max(0.3, min(1.0, 0.3 + under * 5))

        if fill_fraction > 0.0:
            executed = qty * fill_fraction
            notional = executed * fill_price
            if side == "BUY":
                if self._balances[quote]["free"] + 1e-12 < notional:
                    return {"code": 1, "msg": "Insufficient balance in demo"}
                self._balances[quote]["free"] -= notional
                self._balances[base]["free"] += executed
                inv = self._inventory.get(base, {"qty": 0.0, "avg": 0.0})
                new_qty = inv["qty"] + executed
                new_avg = ((inv["avg"] * inv["qty"]) + notional) / max(new_qty, 1e-12)
                self._inventory[base] = {"qty": new_qty, "avg": new_avg}
            else:
                if self._balances[base]["free"] + 1e-12 < executed:
                    return {"code": 1, "msg": "Insufficient balance in demo"}
                self._balances[base]["free"] -= executed
                self._balances[quote]["free"] += notional
                inv = self._inventory.get(base, {"qty": 0.0, "avg": 0.0})
                avg = inv.get("avg", 0.0)
                self._realized_pnl_usdt += (fill_price - avg) * executed
                new_qty = max(0.0, inv.get("qty", 0.0) - executed)
                if new_qty <= 1e-12:
                    self._inventory.pop(base, None)
                else:
                    self._inventory[base] = {"qty": new_qty, "avg": avg}
            status = "FILLED" if abs(executed - qty) <= 1e-12 else "PARTIALLY_FILLED"
            self._trade_log.append({"symbol": sym, "side": side, "price": fill_price, "qty": executed, "type": typ})

        order = {
            "symbol": sym,
            "orderId": order_id,
            "status": status,
            "type": typ,
            "side": side,
            "price": f"{price}",
            "executedQty": f"{executed}",
        }
        if status != "FILLED":
            self._orders[order_id] = order
        return order

    async def cancel_order(self, params: Dict[str, str]) -> Dict[str, Any]:
        oid = params.get("orderId")
        if oid and oid in self._orders:
            o = self._orders.pop(oid)
            o["status"] = "CANCELED"
            return o
        return {"code": 1, "msg": "not found"}

    async def demo_report(self) -> Dict[str, Any]:
        equity = 0.0
        for asset, info in self._balances.items():
            qty = info.get("free", 0.0) + info.get("locked", 0.0)
            px = await self._asset_usdt_price(asset)
            equity += qty * px
        unreal = 0.0
        positions = []
        for asset, inv in self._inventory.items():
            qty = inv.get("qty", 0.0)
            avg = inv.get("avg", 0.0)
            px = await self._asset_usdt_price(asset)
            upnl = (px - avg) * qty
            unreal += upnl
            positions.append({"asset": asset, "qty": qty, "avg": avg, "mark": px, "uPnL": upnl})
        return {
            "equityUSDT": equity,
            "realizedPnLUSDT": self._realized_pnl_usdt,
            "unrealizedPnLUSDT": unreal,
            "positions": positions,
            "openOrders": list(self._orders.values()),
            "trades": self._trade_log[-50:],
        }

    async def _asset_usdt_price(self, asset: str) -> float:
        a = asset.upper()
        if a == "USDT":
            return 1.0
        sym = f"{a}USDT"
        try:
            p = await self._mark_price(sym)
            return p if p > 0 else 0.0
        except Exception:
            return 0.0

    def _ensure_asset(self, a: str) -> None:
        self._balances.setdefault(a.upper(), {"free": 0.0, "locked": 0.0})

    @staticmethod
    def _split_symbol(sym: str) -> tuple[str, str]:
        s = sym.upper()
        for q in ("USDT", "USDC", "BTC", "ETH"):
            if s.endswith(q):
                return s[:-len(q)], q
        return s, "USDT"

