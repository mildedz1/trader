from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from app.strategy_engine.engine import OrderIntent


@dataclass
class GridConfig:
    symbol: str = "btc_usdt"  # LBank spot symbol style
    levels_per_side: int = 6
    mode: str = "percent"  # 'percent' | 'arithmetic'
    upper_pct: float = 0.03
    lower_pct: float = 0.03
    quote_per_order: float = 20.0
    recenter_on_break: bool = True
    kill_switch_pct: float = 0.06
    recalc_sec: int = 5
    default_stop_loss_pct: float = 0.02
    default_take_profit_pct: float = 0.02


def _build_levels(center: float, cfg: GridConfig) -> Tuple[List[float], List[float], float, float]:
    n = cfg.levels_per_side
    up = center * (1 + cfg.upper_pct)
    lo = center * (1 - cfg.lower_pct)
    if cfg.mode == "percent":
        buys = [center * ((lo / center) ** ((i + 1) / n)) for i in range(n)][::-1]
        sells = [center * ((up / center) ** ((i + 1) / n)) for i in range(n)]
    else:
        step = (up - lo) / (2 * n)
        buys = [center - step * (i + 1) for i in range(n)][::-1]
        sells = [center + step * (i + 1) for i in range(n)]
    return buys, sells, lo, up


def _format_decimal(value: float) -> str:
    # LBank accepts string decimals; keep as plain string
    return f"{value:.8f}".rstrip("0").rstrip(".")


@dataclass
class GridSpotStrategy:
    scope: str = "spot"
    cfg: GridConfig = field(default_factory=GridConfig)

    # runtime state
    _center: float | None = None
    _band: Tuple[float, float] | None = None
    _last_recalc_ts: float = 0.0
    _active_prices: Dict[str, str] = field(default_factory=dict)  # price -> side

    async def on_startup(self, ctx) -> None:
        price = await self._fetch_last_price(ctx)
        if price is None:
            return
        self._center = price
        buys, sells, lo, up = _build_levels(price, self.cfg)
        self._band = (lo, up)
        # Do NOT pre-populate active levels; emit initial placement intents in on_signal
        self._active_prices.clear()

    async def on_tick(self, ctx, market: Dict[str, Any]) -> None:
        now = time.time()
        if now - self._last_recalc_ts < self.cfg.recalc_sec:
            return
        last = await self._fetch_last_price(ctx)
        if last is None:
            return
        if self._center is None:
            self._center = last
        self._last_recalc_ts = now
        lo, up = self._band if self._band else (last, last)
        # recenter logic
        if self.cfg.recenter_on_break and (last < lo or last > up):
            self._center = last
            buys, sells, lo, up = _build_levels(last, self.cfg)
            self._band = (lo, up)
            # Clear so on_signal will emit refreshed grid placement intents
            self._active_prices.clear()
        elif (not self.cfg.recenter_on_break) and self._center:
            dist = abs(last - self._center) / self._center
            if dist > self.cfg.kill_switch_pct:
                # In a full implementation, cancel all here
                self._active_prices.clear()

    async def on_signal(self, ctx) -> List[OrderIntent]:
        intents: List[OrderIntent] = []
        if self._center is None:
            return intents
        buys, sells, lo, up = _build_levels(self._center, self.cfg)
        desired = {**{_format_decimal(p): "buy" for p in buys}, **{_format_decimal(p): "sell" for p in sells}}

        # Place missing levels (compared to active set)
        for price_str, side in desired.items():
            if price_str not in self._active_prices:
                price = float(price_str)
                amount = self.cfg.quote_per_order / price
                # basic SL/TP around the level price
                sl = price * (1 - self.cfg.default_stop_loss_pct) if side == "buy" else price * (1 + self.cfg.default_stop_loss_pct)
                tp = price * (1 + self.cfg.default_take_profit_pct) if side == "buy" else price * (1 - self.cfg.default_take_profit_pct)
                intents.append(
                    OrderIntent(
                        symbol=self.cfg.symbol,
                        side=side,
                        type="limit",  # engine will map to maker when placing
                        quantity=_format_decimal(amount),
                        price=price_str,
                        client_order_id=f"grid_{side}_{price_str}",
                        stop_loss=_format_decimal(sl),
                        take_profit=_format_decimal(tp),
                    )
                )
                self._active_prices[price_str] = side
        return intents

    async def risk_check(self, ctx, order: OrderIntent) -> bool:
        # Basic min notional: 5 USDT assumed for spot is usually lower; adjust as needed
        try:
            notional = float(order.quantity) * (float(order.price) if order.price else 0.0)
        except Exception:
            return False
        return notional >= 5.0

    async def _fetch_last_price(self, ctx) -> float | None:
        if not ctx.spot_client:
            return None
        symbols_to_try = [self.cfg.symbol]
        if self.cfg.symbol.lower() != self.cfg.symbol:
            symbols_to_try.append(self.cfg.symbol.lower())
        if self.cfg.symbol.upper() != self.cfg.symbol:
            symbols_to_try.append(self.cfg.symbol.upper())
        for sym in symbols_to_try:
            try:
                data = await ctx.spot_client.ticker_price(sym)
                if isinstance(data, dict):
                    base = data.get("data") or data
                    # Direct scalar price
                    for key in ("price", "last", "lastPrice", "latest", "close"):
                        if key in base and isinstance(base[key], (str, int, float)):
                            return float(base[key])
                    # List under data
                    if isinstance(base, list) and base:
                        # Find matching symbol if present
                        def extract_price(obj: dict) -> float | None:
                            for k in ("price", "last", "lastPrice", "latest", "close"):
                                if k in obj:
                                    try:
                                        return float(obj[k])
                                    except Exception:
                                        return None
                            return None
                        cand = None
                        for obj in base:
                            if isinstance(obj, dict) and obj.get("symbol") in {sym, sym.lower(), sym.upper()}:
                                cand = extract_price(obj)
                                if cand is not None:
                                    return cand
                        # fallback first item
                        if isinstance(base[0], dict):
                            cand = extract_price(base[0])
                            if cand is not None:
                                return cand
                    # Nested ticker list
                    if isinstance(base, dict) and isinstance(base.get("ticker"), list) and base["ticker"]:
                        for obj in base["ticker"]:
                            if not isinstance(obj, dict):
                                continue
                            if obj.get("symbol") in {sym, sym.lower(), sym.upper()}:
                                for k in ("price", "last", "latest", "close"):
                                    if k in obj:
                                        return float(obj[k])
                        obj = base["ticker"][0]
                        for k in ("price", "last", "latest", "close"):
                            if k in obj:
                                return float(obj[k])
            except Exception:
                continue
        return None

    async def describe(self, ctx) -> Dict[str, Any]:
        # Show required conditions and current state
        last = await self._fetch_last_price(ctx)
        buys, sells, lo, up = ([], [], None, None)
        if self._center is not None:
            b, s, l, u = _build_levels(self._center, self.cfg)
            buys, sells, lo, up = b, s, l, u
        return {
            "scope": self.scope,
            "symbol": self.cfg.symbol,
            "required": {
                "min_notional_usdt": 5.0,
                "levels_per_side": self.cfg.levels_per_side,
                "grid_band_pct": [self.cfg.lower_pct, self.cfg.upper_pct],
                "recenter_on_break": self.cfg.recenter_on_break,
            },
            "current": {
                "center": self._center,
                "band": [lo, up] if lo and up else None,
                "last_price": last,
                "active_levels": len(self._active_prices),
            },
            "ready": bool(self._center and last),
        }


def get_strategy():
    return GridSpotStrategy()
