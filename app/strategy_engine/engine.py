from __future__ import annotations

import asyncio
import importlib
import pkgutil
from dataclasses import dataclass
from typing import Any, Dict, List, Protocol

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


@dataclass
class StrategyContext:
    mode: str  # paper/dry-run/live
    spot_client: Any | None
    perp_client: Any | None
    submit_order: Any  # callable to queue orders


class StrategyEngine:
    def __init__(self, spot_client: Any | None = None, perp_client: Any | None = None) -> None:
        self.strategies: Dict[str, StrategyPlugin] = {}
        self.enabled: Dict[str, bool] = {}
        self.mode: str = "paper"
        self._bg_task: asyncio.Task | None = None
        self._market_snapshot: Dict[str, Any] = {}
        self.spot_client = spot_client
        self.perp_client = perp_client

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

    async def _loop(self) -> None:
        ctx = StrategyContext(
            mode=self.mode,
            spot_client=self.spot_client,
            perp_client=self.perp_client,
            submit_order=self._submit_order,
        )
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
                    for intent in intents:
                        ok = await plugin.risk_check(ctx, intent)
                        if ok:
                            await self._submit_order(intent)
                except Exception as exc:
                    logger.error("strategy.tick.error", name=name, error=str(exc))
            await asyncio.sleep(1.0)

    async def _submit_order(self, intent: OrderIntent) -> None:
        # For now, just log intent; integration to order queue can be added
        logger.info("strategy.order.intent", intent=intent.__dict__)

    async def start(self) -> None:
        if self._bg_task is None or self._bg_task.done():
            self._bg_task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._bg_task:
            self._bg_task.cancel()
            with contextlib.suppress(Exception):
                await self._bg_task

