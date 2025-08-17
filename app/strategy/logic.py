from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass
from typing import Dict, List, Tuple

from loguru import logger

from ..core.config import Settings
from ..core.state import WorkerState
from ..exchange_adapter.base import ExchangeAdapter
from .indicators import ema, rsi, crossed_up


@dataclass
class StrategyResult:
	should_long: bool
	should_exit: bool
	ema_fast: float
	ema_slow: float
	rsi: float


def evaluate_strategy(closes: List[float], settings: Settings) -> StrategyResult:
	ema_fast_series = ema(closes, settings.ema_fast)
	ema_slow_series = ema(closes, settings.ema_slow)
	rsi_series = rsi(closes, settings.rsi_period)

	last_ema_fast = ema_fast_series[-1]
	last_ema_slow = ema_slow_series[-1]
	last_rsi = rsi_series[-1]

	trend_ok = last_ema_fast > last_ema_slow
	entry_cross = crossed_up(rsi_series, settings.rsi_entry)
	should_long = trend_ok and entry_cross
	should_exit = last_rsi >= settings.rsi_exit or not trend_ok

	return StrategyResult(
		should_long=should_long,
		should_exit=should_exit,
		ema_fast=last_ema_fast,
		ema_slow=last_ema_slow,
		rsi=last_rsi,
	)


async def compute_position_size(adapter: ExchangeAdapter, settings: Settings, price: float) -> Tuple[float, float]:
	bal = await adapter.fetch_balance()
	free = bal.get("free") or bal.get("total") or {}
	quote_free = float(free.get("USDT", 0))
	if settings.risk_position_mode == "percent_of_balance":
		quote_to_use = quote_free * float(settings.risk_position_size)
	else:
		quote_to_use = float(settings.risk_position_size)
	quote_to_use = max(0.0, min(quote_to_use, quote_free))
	amount_base = 0.0 if price <= 0 else quote_to_use / price
	return amount_base, quote_to_use


async def run_tick(adapter: ExchangeAdapter, state: WorkerState, settings: Settings, closes: List[float]) -> Dict:
	res = evaluate_strategy(closes, settings)
	state.last_signal = f"ema_fast={res.ema_fast:.2f} ema_slow={res.ema_slow:.2f} rsi={res.rsi:.2f} long={res.should_long} exit={res.should_exit}"

	# Update heartbeat
	state.heartbeat(settings.heartbeat_path)

	if state.is_paused:
		return {"status": "paused", "signal": state.last_signal}

	# Enforce daily reset and loss limit
	bal = await adapter.fetch_balance()
	quote = float((bal.get("total") or {}).get("USDT", 0.0))
	base = float((bal.get("total") or {}).get("BTC", 0.0))
	ticker = await adapter.fetch_ticker(settings.symbol)
	price = float(ticker.get("last") or ticker.get("close") or 0.0)
	current_equity = quote + base * price
	if state.should_reset_day(settings.reset_hour_utc) or state.equity_start_of_day <= 0:
		state.reset_day(current_equity)
	else:
		state.update_daily_pnl(current_equity)
	if state.reached_daily_loss_limit(settings.max_daily_loss_pct):
		state.is_paused = True
		logger.warning("Daily loss limit reached. Pausing trading.")
		return {"status": "paused_loss_limit", "signal": state.last_signal}

	# Position management
	if state.position.is_long:
		if res.should_exit:
			amount_base = state.position.quantity
			if amount_base > 0:
				order = await adapter.create_market_sell_order(settings.symbol, amount_base)
				state.position.reset()
				logger.info(f"Exit long: {order}")
				return {"status": "sold", "order": order, "signal": state.last_signal}
			else:
				state.position.reset()
				return {"status": "flat_reset", "signal": state.last_signal}
		else:
			return {"status": "holding", "signal": state.last_signal}
	else:
		if res.should_long:
			amount_base, amount_quote = await compute_position_size(adapter, settings, price)
			if amount_quote <= 0 or amount_base <= 0:
				return {"status": "insufficient_funds", "signal": state.last_signal}
			order = await adapter.create_market_buy_order(settings.symbol, amount_quote)
			state.position.is_long = True
			state.position.entry_price = price
			state.position.quantity = amount_base
			logger.info(f"Enter long: {order}")
			return {"status": "bought", "order": order, "signal": state.last_signal}
		else:
			return {"status": "no_signal", "signal": state.last_signal}