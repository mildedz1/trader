from __future__ import annotations

import asyncio
import importlib
import pkgutil
from dataclasses import dataclass
from typing import Any, Dict, List, Protocol, Callable, Awaitable, Optional
import contextlib

from app.logging import logger


@dataclass
class OrderIntent:
    symbol: str
    side: str  # buy/sell
    type: str  # limit/market
    quantity: str
    price: str | None = None
    client_order_id: str | None = None


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
            self.enabled[name] = value

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
                    if self.mode == "signal":
                        await self._notify_batch(name, permitted, live=False)
                    else:  # live
                        # Place live orders; also send batch notification
                        for intent in permitted:
                            await self._place_live(intent, name)
                        await self._notify_batch(name, permitted, live=True)
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
        # TODO: integrate with LBank order queue respecting rate limits
        # For now, reuse notifier to mark as live placeholder
        logger.info("strategy.order.live", intent=intent.__dict__)
        if self.notifier is not None:
            payload = {
                "event": "order_live",
                "strategy": strategy_name,
                "symbol": intent.symbol,
                "side": intent.side,
                "type": intent.type,
                "quantity": intent.quantity,
                "price": intent.price,
                "clientOrderId": intent.client_order_id,
            }
            try:
                await self.notifier("order_live", payload)
            except Exception:
                pass

    async def _notify_batch(self, strategy_name: str, intents: List[OrderIntent], live: bool) -> None:
        if self.notifier is None:
            return
        event = "order_live_batch" if live else "order_intent_batch"
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
            with contextlib.suppress(Exception):
                await self._bg_task

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

