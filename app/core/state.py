from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional, Dict


@dataclass
class Position:
	is_long: bool = False
	entry_price: float = 0.0
	quantity: float = 0.0  # base amount (e.g., ETH)

	def reset(self) -> None:
		self.is_long = False
		self.entry_price = 0.0
		self.quantity = 0.0


@dataclass
class WorkerState:
	is_paused: bool = False
	last_signal: Optional[str] = None
	position: Position = field(default_factory=Position)
	equity_start_of_day: float = 0.0
	daily_pnl: float = 0.0
	last_reset_day: Optional[int] = None
	last_heartbeat_ts: float = 0.0
	last_price: float = 0.0

	# Strategy context for status rendering
	last_strategy_id: Optional[str] = None
	last_metrics: Dict[str, float] = field(default_factory=dict)
	last_decision_long: bool = False
	last_decision_exit: bool = False
	last_candle_ts: Optional[int] = None  # ms

	# Debounce / Cooldown / Lock
	last_action_candle_ts: Optional[int] = None
	cooldown_candles_remaining: int = 0
	order_lock: bool = False

	# Notifier (set by bot)
	notify: Optional[Callable[[str], Awaitable[None]]] = None

	# Balance provider for bot UI
	balance_provider: Optional[Callable[[], Awaitable[str]]] = None
	position_overview: Optional[Callable[[], Awaitable[str]]] = None

	# Manual actions (wired at startup)
	manual_buy: Optional[Callable[[], Awaitable[str]]] = None
	manual_close: Optional[Callable[[], Awaitable[str]]] = None
	check_signal: Optional[Callable[[], Awaitable[str]]] = None
	# Force actions (futures):
	manual_force_long: Optional[Callable[[], Awaitable[str]]] = None
	manual_force_short: Optional[Callable[[], Awaitable[str]]] = None

	def heartbeat(self, heartbeat_path: str) -> None:
		self.last_heartbeat_ts = time.time()
		os.makedirs(os.path.dirname(heartbeat_path), exist_ok=True)
		with open(heartbeat_path, "w", encoding="utf-8") as f:
			f.write(str(self.last_heartbeat_ts))

	def should_reset_day(self, reset_hour_utc: int) -> bool:
		utc = time.gmtime()
		day_key = utc.tm_yday
		if self.last_reset_day != day_key and utc.tm_hour >= reset_hour_utc:
			return True
		return False

	def reset_day(self, current_equity: float) -> None:
		self.equity_start_of_day = current_equity
		self.daily_pnl = 0.0
		self.last_reset_day = time.gmtime().tm_yday

	def update_daily_pnl(self, current_equity: float) -> None:
		self.daily_pnl = current_equity - self.equity_start_of_day

	def reached_daily_loss_limit(self, max_daily_loss_pct: float) -> bool:
		if self.equity_start_of_day <= 0:
			return False
		loss_pct = -100.0 * min(self.daily_pnl, 0.0) / self.equity_start_of_day
		return loss_pct >= max_daily_loss_pct