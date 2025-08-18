from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, Optional


@dataclass
class WorkerState:
	is_paused: bool = False
	last_signal: Optional[str] = None
	last_metrics: Dict[str, float] = field(default_factory=dict)
	last_candle_ts: Optional[int] = None

	# Bound at runtime
	balance_provider: Optional[Callable[[], Awaitable[str]]] = None
	manual_force_long: Optional[Callable[[], Awaitable[str]]] = None
	manual_force_short: Optional[Callable[[], Awaitable[str]]] = None
	manual_buy: Optional[Callable[[], Awaitable[str]]] = None
	manual_close: Optional[Callable[[], Awaitable[str]]] = None
	diagnose: Optional[Callable[[], Awaitable[str]]] = None