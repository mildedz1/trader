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
        self._active_prices = {**{_format_decimal(p): "buy" for p in buys}, **{_format_decimal(p): "sell" for p in sells}}

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
            self._active_prices.clear()
            self._active_prices.update({**{_format_decimal(p): "buy" for p in buys}, **{_format_decimal(p): "sell" for p in sells}})
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
                intents.append(
                    OrderIntent(
                        symbol=self.cfg.symbol,
                        side=side,
                        type="limit",  # engine will map to maker when placing
                        quantity=_format_decimal(amount),
                        price=price_str,
                        client_order_id=f"grid_{side}_{price_str}",
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
        try:
            data = await ctx.spot_client.ticker_price(self.cfg.symbol)
            # Accept variations
            if isinstance(data, dict):
                d = data.get("data") or data
                for key in ("price", "last", "lastPrice"):
                    if key in d:
                        return float(d[key])
        except Exception:
            return None
        return None


def get_strategy():
    return GridSpotStrategy()
