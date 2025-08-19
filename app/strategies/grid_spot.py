from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from app.strategy_engine.engine import OrderIntent


@dataclass
class GridConfig:
    symbol: str = "trx_usdt"  # LBank spot symbol style
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
    order_sizing: str = "fixed_total_pct"  # "static" | "balance_pct" | "fixed_total_pct"
    balance_pct_per_order: float = 10.0  # percent of free quote per order if balance_pct
    total_budget_usdt: float = 2.8  # used when order_sizing = fixed_total_pct
    per_order_pct_of_total: float = 20.0  # percent of total budget per order
    min_notional_usdt: float = 0.0  # min notional for live; in signal mode ignored
    order_kind: str = "market"  # "limit" | "market"
    cadence_sec: int = 300  # resend signal pack every N seconds even if no recenter


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
    _last_signal_ts: float = 0.0
    _recenter_pending: bool = False
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
        self._recenter_pending = True
        # force immediate signal pack on startup
        self._last_signal_ts = 0.0

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
            self._recenter_pending = True
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

        now = time.time()

        # Determine sizing from balance if requested
        free_quote, free_base = await self._get_free_balances(ctx)
        def per_order_amount(side: str, price: float) -> float:
            if self.cfg.order_sizing == "balance_pct" and free_quote is not None:
                quote_budget = (free_quote * (self.cfg.balance_pct_per_order / 100.0))
            elif self.cfg.order_sizing == "fixed_total_pct":
                quote_budget = (self.cfg.total_budget_usdt * (self.cfg.per_order_pct_of_total / 100.0))
            else:
                quote_budget = self.cfg.quote_per_order
            amt = quote_budget / price
            # In signal mode, don't cap sells by balance; in live, cap by base
            if ctx.mode == "live":
                if side == "sell" and free_base is not None and len(sells) > 0:
                    amt = min(amt, max(0.0, free_base / len(sells)))
            return max(0.0, amt)

        def add_intent(side: str, price_str: str) -> None:
            price = float(price_str)
            amount = per_order_amount(side, price)
            if amount <= 0:
                return
            sl = price * (1 - self.cfg.default_stop_loss_pct) if side == "buy" else price * (1 + self.cfg.default_stop_loss_pct)
            tp = price * (1 + self.cfg.default_take_profit_pct) if side == "buy" else price * (1 - self.cfg.default_take_profit_pct)
            kind = self.cfg.order_kind
            # For market orders, engine will set price=0; omit price in intent
            intent_price = None if kind == "market" else price_str
            intents.append(
                OrderIntent(
                    symbol=self.cfg.symbol,
                    side=side,
                    type=kind,
                    quantity=_format_decimal(amount),
                    price=intent_price,
                    client_order_id=f"grid_{side}_{price_str}",
                    stop_loss=_format_decimal(sl),
                    take_profit=_format_decimal(tp),
                )
            )

        if self._recenter_pending or not self._active_prices:
            # Emit initial/recenter pack: pick at most 3 evenly spaced per side
            def pick(prices: List[float], k: int) -> List[str]:
                n = len(prices)
                if n <= k:
                    return [_format_decimal(p) for p in prices]
                idxs = [round(i * (n - 1) / (k - 1)) for i in range(k)]
                seen = set()
                out = []
                for i in idxs:
                    if i not in seen:
                        out.append(_format_decimal(prices[i]))
                        seen.add(i)
                return out
            picked_buys = pick(buys, 6)
            picked_sells = pick(sells, 6)
            for ps in picked_buys:
                add_intent("buy", ps)
                self._active_prices[ps] = "buy"
            for ps in picked_sells:
                add_intent("sell", ps)
                self._active_prices[ps] = "sell"
            self._recenter_pending = False

        if intents:
            self._last_signal_ts = now
        return intents

    async def risk_check(self, ctx, order: OrderIntent) -> bool:
        # In signal mode, always allow signal
        if ctx.mode == "signal":
            return True
        try:
            notional = float(order.quantity) * (float(order.price) if order.price else 0.0)
        except Exception:
            return False
        min_notional = max(0.0, self.cfg.min_notional_usdt)
        return notional >= min_notional

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
                "min_notional_usdt": self.cfg.min_notional_usdt,
                "levels_per_side": self.cfg.levels_per_side,
                "grid_band_pct": [self.cfg.lower_pct, self.cfg.upper_pct],
                "recenter_on_break": self.cfg.recenter_on_break,
                "order_sizing": self.cfg.order_sizing,
                "balance_pct_per_order": self.cfg.balance_pct_per_order if self.cfg.order_sizing == "balance_pct" else None,
                "fixed_total": {
                    "total_budget_usdt": self.cfg.total_budget_usdt,
                    "per_order_pct": self.cfg.per_order_pct_of_total,
                } if self.cfg.order_sizing == "fixed_total_pct" else None,
                "cadence_sec": self.cfg.cadence_sec,
            },
            "current": {
                "center": self._center,
                "band": [lo, up] if lo and up else None,
                "last_price": last,
                "active_levels": len(self._active_prices),
            },
            "ready": bool(self._center and last),
        }

    async def _get_free_balances(self, ctx) -> tuple[float | None, float | None]:
        # returns (free_quote, free_base)
        try:
            if not ctx.spot_client:
                return None, None
            resp = await ctx.spot_client.user_info_account()
            base, quote = self._parse_symbol_assets(self.cfg.symbol)
            free_base = None
            free_quote = None
            balances = []
            if isinstance(resp, dict):
                d = resp.get("data") or resp
                balances = d.get("balances") or d.get("balance") or []
            for b in balances:
                asset = (b.get("asset") or b.get("currency") or b.get("coin") or "").lower()
                free = b.get("free") or b.get("available")
                try:
                    fv = float(str(free)) if free is not None else 0.0
                except Exception:
                    fv = 0.0
                if asset == base:
                    free_base = fv
                if asset == quote:
                    free_quote = fv
            return free_quote, free_base
        except Exception:
            return None, None

    @staticmethod
    def _parse_symbol_assets(symbol: str) -> tuple[str, str]:
        s = symbol.lower()
        if "_" in s:
            a, q = s.split("_", 2)
            return a, q
        if "-" in s:
            a, q = s.split("-", 2)
            return a, q
        # fallback guess
        if s.endswith("usdt"):
            return s[:-4], "usdt"
        return s, "usdt"


def get_strategy():
    return GridSpotStrategy()
