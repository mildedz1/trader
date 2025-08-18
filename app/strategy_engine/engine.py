from __future__ import annotations

import asyncio
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
    async def on_startup(self, ctx: "StrategyContext") -> None: ...
    async def on_tick(self, ctx: "StrategyContext", market: Dict[str, Any]) -> None: ...
    async def on_signal(self, ctx: "StrategyContext") -> List[OrderIntent]: ...
    async def risk_check(self, ctx: "StrategyContext", order: OrderIntent) -> bool: ...


@dataclass
class StrategyContext:
    mode: str  # paper/dry-run/live


class StrategyEngine:
    def __init__(self) -> None:
        self.strategies: Dict[str, StrategyPlugin] = {}
        self.mode: str = "paper"

    def register(self, name: str, plugin: StrategyPlugin) -> None:
        self.strategies[name] = plugin

    async def start(self) -> None:
        ctx = StrategyContext(mode=self.mode)
        for name, plugin in self.strategies.items():
            try:
                await plugin.on_startup(ctx)
            except Exception as exc:
                logger.error("strategy.startup.error", name=name, error=str(exc))

