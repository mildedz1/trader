from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RiskLimits:
    min_notional_usdt: float = 5.0
    max_order_usdt: float = 10000.0
    max_open_positions: int = 10


class RiskManager:
    def __init__(self, limits: RiskLimits | None = None) -> None:
        self.limits = limits or RiskLimits()

    def check_min_notional(self, notional_usdt: float) -> bool:
        return notional_usdt >= self.limits.min_notional_usdt

    def check_max_order(self, notional_usdt: float) -> bool:
        return notional_usdt <= self.limits.max_order_usdt
