from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from ..core.config import Settings
from .indicators import ema, macd


@dataclass
class StrategyResult:
	should_long: bool
	should_exit: bool
	extra: Dict[str, float]


def evaluate_macd_zero_trend(closes: List[float], settings: Settings) -> StrategyResult:
	ema_fast = ema(closes, 50)
	ema_slow = ema(closes, 200)
	m, s, h = macd(closes, 12, 26, 9)
	trend_ok = bool(ema_fast[-1] > ema_slow[-1])
	zero_up = bool(h[-2] <= 0 and h[-1] > 0) if len(h) >= 2 else False
	zero_down = bool(h[-2] >= 0 and h[-1] < 0) if len(h) >= 2 else False
	return StrategyResult(
		should_long=trend_ok and zero_up,
		should_exit=(not trend_ok) or zero_down,
		extra={"trend_ok": 1.0 if trend_ok else 0.0, "zero_up": 1.0 if zero_up else 0.0, "zero_down": 1.0 if zero_down else 0.0},
	)