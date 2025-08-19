from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple
import time

from app.strategy_engine.engine import OrderIntent


@dataclass
class GridPerpConfig:
    symbol: str = "BTC_USDT"
    levels_per_side: int = 4
    upper_pct: float = 0.02
    lower_pct: float = 0.02
    order_kind: str = "limit"  # limit/market
    recalc_sec: int = 5


def _build_levels(center: float, cfg: GridPerpConfig) -> Tuple[List[float], List[float]]:
    n = cfg.levels_per_side
    up = center * (1 + cfg.upper_pct)
    lo = center * (1 - cfg.lower_pct)
    buys = [center * ((lo / center) ** ((i + 1) / n)) for i in range(n)][::-1]
    sells = [center * ((up / center) ** ((i + 1) / n)) for i in range(n)]
    return buys, sells


def _fmt(x: float) -> str:
    return f"{x:.8f}".rstrip("0").rstrip(".")


@dataclass
class GridPerpBtcStrategy:
    scope: str = "perp"
    cfg: GridPerpConfig = field(default_factory=GridPerpConfig)
    _center: float | None = None
    _last_recalc_ts: float = 0.0

    async def on_startup(self, ctx) -> None:
        last = await self._last_price(ctx)
        if last is None:
            return
        self._center = last

    async def on_tick(self, ctx, market: Dict[str, Any]) -> None:
        now = time.time()
        if now - self._last_recalc_ts < self.cfg.recalc_sec:
            return
        last = await self._last_price(ctx)
        if last is None:
            return
        self._center = last
        self._last_recalc_ts = now

    async def on_signal(self, ctx) -> List[OrderIntent]:
        if not self._center:
            return []
        buys, sells = _build_levels(self._center, self.cfg)
        intents: List[OrderIntent] = []
        kind = self.cfg.order_kind
        # pick one buy/sell each tick around center
        if buys:
            intents.append(OrderIntent(symbol=self.cfg.symbol, side="buy", type=kind, quantity=_fmt(0.001), price=None if kind=="market" else _fmt(buys[0])))
        if sells:
            intents.append(OrderIntent(symbol=self.cfg.symbol, side="sell", type=kind, quantity=_fmt(0.001), price=None if kind=="market" else _fmt(sells[0])))
        return intents

    async def risk_check(self, ctx, order: OrderIntent) -> bool:
        return True

    async def describe(self, ctx) -> Dict[str, Any]:
        last = await self._last_price(ctx)
        return {"scope": self.scope, "symbol": self.cfg.symbol, "center": self._center, "last": last}

    async def _last_price(self, ctx) -> float | None:
        if not ctx.perp_client:
            return None
        try:
            px = await ctx.perp_client.ticker_price(self.cfg.symbol)
            return float(px) if px else None
        except Exception:
            return None


def get_strategy():
    return GridPerpBtcStrategy()

