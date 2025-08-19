from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from app.strategy_engine.engine import OrderIntent


@dataclass
class SamplePerpStrategy:
    scope: str = "perp"

    async def on_startup(self, ctx) -> None:
        return None

    async def on_tick(self, ctx, market: Dict[str, Any]) -> None:
        return None

    async def on_signal(self, ctx) -> List[OrderIntent]:
        return []

    async def risk_check(self, ctx, order: OrderIntent) -> bool:
        return True


def get_strategy():
    return SamplePerpStrategy()
