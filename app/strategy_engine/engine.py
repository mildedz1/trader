from __future__ import annotations

import asyncio
import importlib
import pkgutil
from dataclasses import dataclass
from typing import Any, Dict, List, Protocol, Callable, Awaitable, Optional
import contextlib

from app.logging import logger
from app.ratelimiter import RateLimiter


@dataclass
class OrderIntent:
    symbol: str
    side: str  # buy/sell
    type: str  # limit/market
    quantity: str
    price: str | None = None
    client_order_id: str | None = None
    stop_loss: str | None = None
    take_profit: str | None = None


class StrategyPlugin(Protocol):
    scope: str  # "spot" | "perp" | "both"

    async def on_startup(self, ctx: "StrategyContext") -> None: ...
    async def on_tick(self, ctx: "StrategyContext", market: Dict[str, Any]) -> None: ...
    async def on_signal(self, ctx: "StrategyContext") -> List[OrderIntent]: ...
    async def risk_check(self, ctx: "StrategyContext", order: OrderIntent) -> bool: ...
    async def describe(self, ctx: "StrategyContext") -> Dict[str, Any]: ...


@dataclass
class StrategyContext:
    mode: str  # paper/dry-run/live
    spot_client: Any | None
    perp_client: Any | None
    submit_order: Any  # callable to queue orders


class StrategyEngine:
    def __init__(self, spot_client: Any | None = None, perp_client: Any | None = None, notifier: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None) -> None:
        self.strategies: Dict[str, StrategyPlugin] = {}
        self.enabled: Dict[str, bool] = {}
        self.mode: str = "paper"
        self._bg_task: asyncio.Task | None = None
        self._market_snapshot: Dict[str, Any] = {}
        self.spot_client = spot_client
        self.perp_client = perp_client
        self.notifier = notifier
        self._ratelimiter = RateLimiter()

    def register(self, name: str, plugin: StrategyPlugin) -> None:
        self.strategies[name] = plugin
        self.enabled.setdefault(name, False)

    def unregister(self, name: str) -> None:
        self.strategies.pop(name, None)
        self.enabled.pop(name, None)

    def list(self) -> List[Dict[str, Any]]:
        return [
            {"name": n, "enabled": self.enabled.get(n, False), "scope": getattr(p, "scope", "both")}
            for n, p in self.strategies.items()
        ]

    def set_enabled(self, name: str, value: bool) -> None:
        if name in self.strategies:
            was = self.enabled.get(name, False)
            self.enabled[name] = value
            if value and not was:
                # Run plugin startup when enabling to allow initial signals
                asyncio.create_task(self._startup_plugin(name))

    def load_plugins(self, package: str = "app.strategies") -> List[str]:
        loaded: List[str] = []
        try:
            pkg = importlib.import_module(package)
        except Exception as exc:
            logger.error("strategy.load.import_error", package=package, error=str(exc))
            return loaded
        for modinfo in pkgutil.iter_modules(pkg.__path__, package + "."):
            modname = modinfo.name
            try:
                module = importlib.import_module(modname)
                plugin = None
                if hasattr(module, "get_strategy"):
                    plugin = module.get_strategy()
                elif hasattr(module, "strategy"):
                    plugin = getattr(module, "strategy")
                if plugin is not None:
                    self.register(modname.rsplit(".", 1)[-1], plugin)
                    loaded.append(modname)
            except Exception as exc:
                logger.error("strategy.load.error", module=modname, error=str(exc))
        return loaded

    def _build_ctx(self) -> StrategyContext:
        return StrategyContext(
            mode=self.mode,
            spot_client=self.spot_client,
            perp_client=self.perp_client,
            submit_order=self._submit_order,
        )

    async def _loop(self) -> None:
        ctx = self._build_ctx()
        # Startup hooks
        for name, plugin in self.strategies.items():
            try:
                await plugin.on_startup(ctx)
            except Exception as exc:
                logger.error("strategy.startup.error", name=name, error=str(exc))
        # Tick loop
        while True:
            for name, plugin in list(self.strategies.items()):
                if not self.enabled.get(name, False):
                    continue
                try:
                    await plugin.on_tick(ctx, self._market_snapshot)
                    intents = await plugin.on_signal(ctx)
                    permitted: List[OrderIntent] = []
                    for intent in intents:
                        ok = await plugin.risk_check(ctx, intent)
                        if ok:
                            permitted.append(intent)
                    if not permitted:
                        continue
                    # Only place live orders when mode is explicitly "live".
                    # In any other mode (e.g., signal, paper), just emit signals.
                    if self.mode != "live":
                        # Split by side to avoid mixed confusing packs
                        buys = [i for i in permitted if i.side == "buy"]
                        sells = [i for i in permitted if i.side == "sell"]
                        if buys:
                            await self._notify_batch(name, buys, live=False)
                        if sells:
                            await self._notify_batch(name, sells, live=False)
                    else:  # live
                        # Place live orders; also send batch notification
                        for intent in permitted:
                            await self._place_live(intent, name)
                        # notify by side
                        buys = [i for i in permitted if i.side == "buy"]
                        sells = [i for i in permitted if i.side == "sell"]
                        if buys:
                            await self._notify_batch(name, buys, live=True)
                        if sells:
                            await self._notify_batch(name, sells, live=True)
                except Exception as exc:
                    logger.error("strategy.tick.error", name=name, error=str(exc))
            await asyncio.sleep(1.0)

    async def _submit_order(self, intent: OrderIntent, strategy_name: str) -> None:
        # For now, just log intent; integration to order queue can be added
        logger.info("strategy.order.intent", intent=intent.__dict__)
        if self.notifier is not None:
            payload = {
                "event": "order_intent",
                "strategy": strategy_name,
                "symbol": intent.symbol,
                "side": intent.side,
                "type": intent.type,
                "quantity": intent.quantity,
                "price": intent.price,
                "clientOrderId": intent.client_order_id,
            }
            try:
                await self.notifier("order_intent", payload)
            except Exception:
                pass

    async def _place_live(self, intent: OrderIntent, strategy_name: str) -> None:
        logger.info("strategy.order.live", intent=intent.__dict__)
        # Spot placement
        if self.spot_client and intent.symbol:
            await self._ratelimiter.acquire("trade")
            order_type = None
            if intent.type == "market":
                # MEXC uses MARKET type
                order_type = "MARKET"
            else:
                # MEXC uses LIMIT type
                order_type = "LIMIT"
            # Prefer canonical symbol if available
            used_symbol = intent.symbol
            try:
                if hasattr(self.spot_client, "normalize_symbol"):
                    used_symbol = await self.spot_client.normalize_symbol(intent.symbol)
            except Exception:
                used_symbol = intent.symbol
            params: Dict[str, str] = {
                "symbol": used_symbol,
                "type": order_type,
                "side": ("BUY" if intent.side == "buy" else "SELL"),
                "quantity": intent.quantity,
            }
            # For limit orders include price; for market omit
            if intent.type == "limit":
                used_price = intent.price or "0"
                params["price"] = used_price
            else:
                used_price = "-"
            # Client order id passthrough
            if intent.client_order_id:
                # Constrain client order id to allowed charset for MEXC
                safe = (
                    intent.client_order_id.replace(" ", "_")
                    .replace("/", "_")
                    .replace(".", "_")
                )
                params["clientOrderId"] = safe[:32]
            try:
                resp = await self.spot_client.create_order(params)
                ok = False
                msg = None
                code = None
                if isinstance(resp, dict):
                    # MEXC typically returns order object or error with code/msg
                    ok = not ("code" in resp and resp.get("code") not in ("0", 0))
                    msg = resp.get("msg") or resp.get("message")
                    code = resp.get("code")
                if ok:
                    if self.notifier is not None:
                        await self.notifier("order_placed", {
                            "strategy": strategy_name,
                            "symbol": used_symbol,
                            "side": intent.side,
                            "type": order_type,
                            "quantity": intent.quantity,
                            "price": used_price,
                            "resp": resp,
                        })
                else:
                    if self.notifier is not None:
                        await self.notifier("order_error", {
                            "strategy": strategy_name,
                            "symbol": used_symbol,
                            "side": intent.side,
                            "type": order_type,
                            "quantity": intent.quantity,
                            "price": used_price,
                            "error": f"{code} {msg}",
                            "resp": resp,
                        })
            except Exception as exc:
                if self.notifier is not None:
                    await self.notifier("order_error", {
                        "strategy": strategy_name,
                        "symbol": used_symbol,
                        "side": intent.side,
                        "type": order_type,
                        "quantity": intent.quantity,
                        "price": used_price,
                        "error": str(exc),
                    })

    async def _notify_batch(self, strategy_name: str, intents: List[OrderIntent], live: bool) -> None:
        if self.notifier is None:
            return
        event = "order_live_batch" if live else "order_intent_batch"
        # attach strategy diagnostics if available
        desc: Dict[str, Any] | None = None
        try:
            plugin = self.strategies.get(strategy_name)
            if plugin is not None:
                desc = await plugin.describe(self._build_ctx())
        except Exception:
            desc = None
        payload = {
            "event": event,
            "strategy": strategy_name,
            "mode": self.mode,
            "intents": [
                {
                    "symbol": it.symbol,
                    "side": it.side,
                    "type": it.type,
                    "quantity": it.quantity,
                    "price": it.price,
                    "clientOrderId": it.client_order_id,
                }
                for it in intents
            ],
            "desc": desc,
        }
        try:
            await self.notifier(event, payload)
        except Exception:
            pass

    async def start(self) -> None:
        if self._bg_task is None or self._bg_task.done():
            self._bg_task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._bg_task:
            self._bg_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._bg_task
            self._bg_task = None

    async def describe_all(self) -> List[Dict[str, Any]]:
        ctx = self._build_ctx()
        items: List[Dict[str, Any]] = []
        for name, plugin in self.strategies.items():
            try:
                d = await plugin.describe(ctx)
            except Exception as exc:
                d = {"error": str(exc)}
            items.append({"name": name, "enabled": self.enabled.get(name, False), **d})
        return items

    async def _startup_plugin(self, name: str) -> None:
        plugin = self.strategies.get(name)
        if plugin is None:
            return
        try:
            await plugin.on_startup(self._build_ctx())
        except Exception as exc:
            logger.error("strategy.enable.startup.error", name=name, error=str(exc))

