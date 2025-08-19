from __future__ import annotations

import itertools
from typing import Any, Dict, Optional
import math

from app.http import HttpClient


SPOT_BASE_URL = "https://api.mexc.com/"


class MexcSpotDemoClient:
    def __init__(self, initial_balances: Optional[Dict[str, float]] = None, base_url: str | None = None, slippage_bps: int = 5, enable_partial_fills: bool = True) -> None:
        self.base_url = (base_url or SPOT_BASE_URL).rstrip("/") + "/"
        self.http = HttpClient(self.base_url)
        # balances tracked as {asset: {free: float, locked: float}}
        self._balances: Dict[str, Dict[str, float]] = {}
        init = initial_balances or {"USDT": 100000.0}
        self._initial_balances: Dict[str, float] = {k.upper(): float(v) for k, v in init.items()}
        for asset, amt in init.items():
            self._balances[asset.upper()] = {"free": float(amt), "locked": 0.0}
        self._pair_map: dict[str, str] = {}
        self._orders: Dict[str, Dict[str, Any]] = {}
        self._id_counter = itertools.count(1)
        # demo trading state
        self.is_demo: bool = True
        self._realized_pnl_usdt: float = 0.0
        # running inventory avg cost in USDT for base assets
        self._inventory: Dict[str, Dict[str, float]] = {}  # {asset: {qty, avg_cost_usdt}}
        self._trade_log: list[Dict[str, Any]] = []
        self._slippage_bps = max(0, int(slippage_bps))
        self._partial_fills = bool(enable_partial_fills)

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

        # Market: fill immediately at last price with slippage
        fill_fraction = 0.0
        fill_price = price
        if otype == "MARKET":
            fill_fraction = 1.0
            slip = self._slippage_bps / 10000.0
            if side == "BUY":
                fill_price = last_price * (1.0 + slip)
            else:
                fill_price = last_price * (1.0 - slip)
        elif otype == "LIMIT":
            # If price crosses last, allow partial fills
            if side == "BUY" and last_price >= price:
                # the more it crosses, the higher the fraction
                over = (last_price - price) / max(price, 1e-12)
                fill_fraction = 1.0 if not self._partial_fills else max(0.3, min(1.0, 0.3 + over * 5))
                fill_price = price
            elif side == "SELL" and last_price <= price:
                under = (price - last_price) / max(price, 1e-12)
                fill_fraction = 1.0 if not self._partial_fills else max(0.3, min(1.0, 0.3 + under * 5))
                fill_price = price
        
        if fill_fraction > 0.0:
            executed = qty * fill_fraction
            # Ensure balances
            notional = executed * fill_price
            if side == "BUY":
                if self._balances[quote]["free"] + 1e-12 < notional:
                    return {"code": 700001, "msg": "Insufficient balance in demo"}
                self._balances[quote]["free"] -= notional
                self._balances[base]["free"] += executed
                # inventory avg cost update
                inv = self._inventory.get(base, {"qty": 0.0, "avg": 0.0})
                new_qty = inv["qty"] + executed
                new_avg = ((inv["avg"] * inv["qty"]) + notional) / max(new_qty, 1e-12)
                self._inventory[base] = {"qty": new_qty, "avg": new_avg}
            else:
                if self._balances[base]["free"] + 1e-12 < executed:
                    return {"code": 700001, "msg": "Insufficient balance in demo"}
                self._balances[base]["free"] -= executed
                self._balances[quote]["free"] += notional
                # realized pnl on sell against avg cost
                inv = self._inventory.get(base, {"qty": 0.0, "avg": 0.0})
                avg = inv.get("avg", 0.0)
                self._realized_pnl_usdt += (fill_price - avg) * executed
                new_qty = max(0.0, inv.get("qty", 0.0) - executed)
                if new_qty <= 1e-12:
                    self._inventory.pop(base, None)
                else:
                    self._inventory[base] = {"qty": new_qty, "avg": avg}
            status = "FILLED" if math.isclose(executed, qty, rel_tol=0, abs_tol=1e-12) else "PARTIALLY_FILLED"
            filled_qty = executed
            # log trade
            self._trade_log.append({
                "symbol": sym,
                "side": side,
                "price": fill_price,
                "qty": executed,
                "notional": notional,
                "type": otype,
            })

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

    async def _asset_price_usdt(self, asset: str) -> float:
        a = asset.upper()
        if a == "USDT":
            return 1.0
        sym = f"{a}USDT"
        try:
            t = await self.ticker_price(sym)
            p = float(str(t.get("price") or t.get("last") or 0))
            return p if p > 0 else 0.0
        except Exception:
            return 0.0

    async def demo_report(self) -> Dict[str, Any]:
        # Compute total equity (USDT), realized/unrealized PnL, open orders, positions
        total_equity = 0.0
        unrealized = 0.0
        positions: list[Dict[str, Any]] = []
        # Sum wallet equity
        for asset, info in self._balances.items():
            qty = float(info.get("free", 0.0)) + float(info.get("locked", 0.0))
            px = await self._asset_price_usdt(asset)
            total_equity += qty * px
        # Positions and unrealized
        for asset, inv in self._inventory.items():
            qty = inv.get("qty", 0.0)
            avg = inv.get("avg", 0.0)
            px = await self._asset_price_usdt(asset)
            upnl = (px - avg) * qty
            unrealized += upnl
            positions.append({"asset": asset, "qty": qty, "avg": avg, "mark": px, "uPnL": upnl})
        open_orders = list(self._orders.values())
        return {
            "equityUSDT": total_equity,
            "realizedPnLUSDT": self._realized_pnl_usdt,
            "unrealizedPnLUSDT": unrealized,
            "positions": positions,
            "openOrders": open_orders,
            "trades": self._trade_log[-50:],
        }

