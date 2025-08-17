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
from .indicators import ema, rsi, crossed_up, bollinger_bands, bb_bandwidth, percentile


@dataclass
class StrategyResult:
	should_long: bool
	should_exit: bool
	extra: Dict[str, float]


def evaluate_ema_rsi(closes: List[float], settings: Settings) -> StrategyResult:
	ema_fast_series = ema(closes, settings.ema_fast)
	ema_slow_series = ema(closes, settings.ema_slow)
	rsi_series = rsi(closes, settings.rsi_period)

	last_ema_fast = ema_fast_series[-1]
	last_ema_slow = ema_slow_series[-1]
	last_rsi = rsi_series[-1]
	trend_ok = last_ema_fast > last_ema_slow
	entry_cross = rsi_series[-2] < settings.rsi_entry and rsi_series[-1] >= settings.rsi_entry
	should_long = trend_ok and entry_cross
	should_exit = last_rsi >= settings.rsi_exit or not trend_ok
	return StrategyResult(should_long, should_exit, {
		"ema_fast": last_ema_fast,
		"ema_slow": last_ema_slow,
		"rsi": last_rsi,
	})


def evaluate_bb_breakout(closes: List[float], settings: Settings) -> StrategyResult:
	upper, basis, lower = bollinger_bands(closes, settings.bb_period, settings.bb_std)
	bw = bb_bandwidth(upper, basis, lower)
	# Compute threshold from last 200 bandwidths
	lookback = min(len(bw), settings.bb_bw_lookback)
	bw_tail = [x for x in bw[-lookback:] if x > 0]
	bw_thresh = percentile(bw_tail, settings.bb_bw_pctl) if bw_tail else 0.0
	is_squeeze = bw[-1] <= bw_thresh if bw_tail else False
	# Entry: close crosses above upper band and RSI >= confirm
	rsi_series = rsi(closes, settings.rsi_period)
	cross_up = closes[-2] <= upper[-2] and closes[-1] > upper[-1]
	should_long = bool(is_squeeze and cross_up and rsi_series[-1] >= settings.rsi_confirm)
	# Exit: close below basis OR RSI < 40
	should_exit = bool((closes[-1] < basis[-1]) or (rsi_series[-1] < 40))
	return StrategyResult(should_long, should_exit, {
		"bb_bw": bw[-1] if bw else 0.0,
		"bb_bw_thresh": bw_thresh,
		"rsi": rsi_series[-1] if rsi_series else 0.0,
		"upper": upper[-1] if upper else 0.0,
		"basis": basis[-1] if basis else 0.0,
		"lower": lower[-1] if lower else 0.0,
	})


def select_strategy(closes: List[float], settings: Settings) -> StrategyResult:
	if settings.strategy_id == "bb_breakout":
		return evaluate_bb_breakout(closes, settings)
	return evaluate_ema_rsi(closes, settings)


async def compute_position_size_usdt_capped(adapter: ExchangeAdapter, settings: Settings, price: float) -> Tuple[float, float]:
	bal = await adapter.fetch_balance()
	free = bal.get("free") or bal.get("total") or {}
	usdt_free = float(free.get("USDT", 0))
	usdt_to_use = min(float(settings.risk_position_size), usdt_free, 1.0)
	usdt_to_use = max(0.0, usdt_to_use)
	amount_base = 0.0 if price <= 0 else usdt_to_use / price
	return amount_base, usdt_to_use


async def run_tick(adapter: ExchangeAdapter, state: WorkerState, settings: Settings, closes: List[float], candle_ts: int | None = None) -> Dict:
	# Only act on new closed candle
	if candle_ts is not None:
		if state.last_action_candle_ts is not None and candle_ts <= state.last_action_candle_ts:
			return {"status": "waiting_candle"}

	res = select_strategy(closes, settings)
	state.last_signal = f"{settings.strategy_id} | {res.extra} | long={res.should_long} exit={res.should_exit}"

	# Update heartbeat
	state.heartbeat(settings.heartbeat_path)

	if state.is_paused:
		return {"status": "paused", "signal": state.last_signal}

	# Enforce daily reset and loss limit
	bal = await adapter.fetch_balance()
	quote = float((bal.get("total") or {}).get("USDT", 0.0))
	base = float((bal.get("total") or {}).get(settings.symbol.split("/")[0], 0.0))
	ticker = await adapter.fetch_ticker(settings.symbol)
	price = float(ticker.get("last") or ticker.get("close") or 0.0)
	current_equity = quote + base * price
	if state.should_reset_day(settings.reset_hour_utc) or state.equity_start_of_day <= 0:
		state.reset_day(current_equity)
	else:
		state.update_daily_pnl(current_equity)
	if state.reached_daily_loss_limit(settings.max_daily_loss_pct):
		state.is_paused = True
		msg = "Daily loss limit reached. Pausing trading."
		logger.warning(msg)
		if state.notify:
			await state.notify(msg)
		return {"status": "paused_loss_limit", "signal": state.last_signal}

	# Cooldown handling
	if state.cooldown_candles_remaining > 0:
		state.cooldown_candles_remaining -= 1
		return {"status": "cooldown", "remaining": state.cooldown_candles_remaining}

	# Position management with $1 cap and min-notional checks
	base_ccy = settings.symbol.split("/")[0]
	if state.position.is_long:
		if res.should_exit:
			amount_base = state.position.quantity
			amount_base = min(amount_base, base)  # cannot sell more than available
			if amount_base <= 0:
				state.position.reset()
				return {"status": "flat_reset"}
			# clip notional to $1 cap
			notional = min(amount_base * price, 1.0)
			amount_to_sell = notional / price if price > 0 else 0.0
			if amount_to_sell <= 0:
				return {"status": "noop_sell_zero"}
			# round to lot size
			if hasattr(adapter, "round_amount"):
				amount_to_sell = adapter.round_amount(settings.symbol, amount_to_sell)  # type: ignore[attr-defined]
			# check min-notional/min-amount
			min_cost = 0.0
			min_amount = 0.0
			if hasattr(adapter, "get_market_rules"):
				mr = adapter.get_market_rules(settings.symbol)  # type: ignore[attr-defined]
				min_cost = float(mr.get("min_cost", 0.0))
				min_amount = float(mr.get("min_amount", 0.0))
			if (amount_to_sell * price) < max(min_cost, 0.0) or amount_to_sell < max(min_amount, 0.0):
				msg = f"SELL skipped: below exchange min (amount={amount_to_sell}, notional={amount_to_sell*price:.4f} USDT)"
				logger.warning(msg)
				if state.notify:
					await state.notify(msg)
				return {"status": "sell_min_notional_skip"}
			if state.order_lock:
				return {"status": "locked"}
			state.order_lock = True
			try:
				order = await adapter.create_market_sell_order(settings.symbol, amount_to_sell)
				state.position.reset()
				logger.info(f"Exit long: {order}")
				if candle_ts is not None:
					state.last_action_candle_ts = candle_ts
				# apply cooldown
				state.cooldown_candles_remaining = max(0, int(settings.cooldown_candles_after_exit))
				return {"status": "sold", "order": order, "signal": state.last_signal}
			finally:
				state.order_lock = False
		else:
			return {"status": "holding", "signal": state.last_signal}
	else:
		if res.should_long:
			amount_base_cap, amount_quote_cap = await compute_position_size_usdt_capped(adapter, settings, price)
			if amount_quote_cap <= 0 or amount_base_cap <= 0:
				return {"status": "insufficient_funds", "signal": state.last_signal}
			# respect rounding and min rules
			if hasattr(adapter, "round_amount"):
				amount_base_cap = adapter.round_amount(settings.symbol, amount_base_cap)  # type: ignore[attr-defined]
			min_cost = 0.0
			min_amount = 0.0
			if hasattr(adapter, "get_market_rules"):
				mr = adapter.get_market_rules(settings.symbol)  # type: ignore[attr-defined]
				min_cost = float(mr.get("min_cost", 0.0))
				min_amount = float(mr.get("min_amount", 0.0))
			notional = amount_base_cap * price
			if notional < max(min_cost, 0.0) or amount_base_cap < max(min_amount, 0.0):
				msg = f"BUY skipped: below exchange min (amount={amount_base_cap}, notional={notional:.4f} USDT)"
				logger.warning(msg)
				if state.notify:
					await state.notify(msg)
				return {"status": "buy_min_notional_skip"}
			if state.order_lock:
				return {"status": "locked"}
			state.order_lock = True
			try:
				order = await adapter.create_market_buy_order(settings.symbol, amount_quote_cap)
				state.position.is_long = True
				state.position.entry_price = price
				state.position.quantity = amount_base_cap
				logger.info(f"Enter long: {order}")
				if candle_ts is not None:
					state.last_action_candle_ts = candle_ts
				return {"status": "bought", "order": order, "signal": state.last_signal}
			finally:
				state.order_lock = False
		else:
			return {"status": "no_signal", "signal": state.last_signal}