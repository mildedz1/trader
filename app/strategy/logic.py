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
from .indicators import ema, rsi, macd


@dataclass
class StrategyResult:
	should_long: bool
	should_exit: bool
	extra: Dict[str, float]


def evaluate_macd_zero_trend(closes: List[float], settings: Settings) -> StrategyResult:
	ema_fast_series = ema(closes, settings.ema_fast)
	ema_slow_series = ema(closes, settings.ema_slow)
	macd_line, signal_line, hist = macd(closes, settings.macd_fast, settings.macd_slow, settings.macd_signal)
	trend_ok = ema_fast_series[-1] > ema_slow_series[-1]
	# zero-cross up/down on histogram
	h_prev, h_now = (hist[-2], hist[-1]) if len(hist) >= 2 else (0.0, 0.0)
	zero_up = (h_prev <= 0) and (h_now > 0)
	zero_down = (h_prev >= 0) and (h_now < 0)
	should_long = trend_ok and zero_up
	rsi_now = None
	if settings.rsi_confirm:
		rsi_series = rsi(closes, 14)
		rsi_now = rsi_series[-1]
		should_long = should_long and (rsi_now >= settings.rsi_confirm_level)
	should_exit = (zero_down) or (not trend_ok)
	extra: Dict[str, float] = {
		"ema_fast": ema_fast_series[-1],
		"ema_slow": ema_slow_series[-1],
		"macd_hist_prev": h_prev,
		"macd_hist_now": h_now,
		"trend_ok": 1.0 if trend_ok else 0.0,
		"zero_up": 1.0 if zero_up else 0.0,
		"zero_down": 1.0 if zero_down else 0.0,
	}
	if rsi_now is not None:
		extra["rsi_now"] = float(rsi_now)
	return StrategyResult(
		should_long=bool(should_long),
		should_exit=bool(should_exit),
		extra=extra,
	)


async def compute_position_size_usdt_capped(adapter: ExchangeAdapter, settings: Settings, price: float) -> Tuple[float, float]:
	bal = await adapter.fetch_balance()
	free = bal.get("free") or bal.get("total") or {}
	usdt_free = float(free.get("USDT", 0))
	usdt_to_use = min(float(settings.risk_position_size), usdt_free, 1.0)
	usdt_to_use = max(0.0, usdt_to_use)
	amount_base = 0.0 if price <= 0 else usdt_to_use / price
	return amount_base, usdt_to_use


async def run_tick(adapter: ExchangeAdapter, state: WorkerState, settings: Settings, closes: List[float], candle_ts: int | None = None) -> Dict:
	if candle_ts is not None:
		if state.last_action_candle_ts is not None and candle_ts <= state.last_action_candle_ts:
			return {"status": "waiting_candle"}

	res = evaluate_macd_zero_trend(closes, settings)
	state.last_strategy_id = "macd_zero_trend"
	state.last_metrics = res.extra
	state.last_decision_long = bool(res.should_long)
	state.last_decision_exit = bool(res.should_exit)
	state.last_candle_ts = candle_ts
	state.last_signal = f"macd_zero_trend | {res.extra} | long={res.should_long} exit={res.should_exit}"

	state.heartbeat(settings.heartbeat_path)

	if state.is_paused:
		return {"status": "paused", "signal": state.last_signal}

	bal = await adapter.fetch_balance()
	quote = float((bal.get("total") or {}).get("USDT", 0.0))
	base_ccy = settings.symbol.split("/")[0]
	base = float((bal.get("total") or {}).get(base_ccy, 0.0))
	ticker = await adapter.fetch_ticker(settings.symbol)
	price = float(ticker.get("last") or ticker.get("close") or 0.0)
	current_equity = quote + base * price
	if state.should_reset_day(settings.reset_hour_utc) or state.equity_start_of_day <= 0:
		state.reset_day(current_equity)
	else:
		state.update_daily_pnl(current_equity)
	if state.reached_daily_loss_limit(settings.max_daily_loss_pct):
		state.is_paused = True
		msg = "محدودیت ضرر روزانه فعال شد. ربات موقتا متوقف می‌شود."
		logger.warning("Daily loss limit reached. Pausing trading.")
		if state.notify:
			await state.notify(msg)
		return {"status": "paused_loss_limit", "signal": state.last_signal}

	if state.cooldown_candles_remaining > 0:
		state.cooldown_candles_remaining -= 1
		return {"status": "cooldown", "remaining": state.cooldown_candles_remaining}

	if state.position.is_long:
		if res.should_exit:
			amount_base = min(state.position.quantity, base)
			if amount_base <= 0:
				state.position.reset()
				return {"status": "flat_reset"}
			notional = min(amount_base * price, 1.0)
			amount_to_sell = notional / price if price > 0 else 0.0
			if amount_to_sell <= 0:
				return {"status": "noop_sell_zero"}
			if hasattr(adapter, "round_amount"):
				amount_to_sell = adapter.round_amount(settings.symbol, amount_to_sell)  # type: ignore[attr-defined]
			min_cost = 0.0
			min_amount = 0.0
			if hasattr(adapter, "get_market_rules"):
				mr = adapter.get_market_rules(settings.symbol)  # type: ignore[attr-defined]
				min_cost = float(mr.get("min_cost", 0.0))
				min_amount = float(mr.get("min_amount", 0.0))
			if (amount_to_sell * price) < max(min_cost, 0.0) or amount_to_sell < max(min_amount, 0.0):
				msg = f"فروش انجام نشد: کمتر از حداقل صرافی (amount={amount_to_sell}, notional={amount_to_sell*price:.4f} USDT)"
				logger.warning("SELL skipped: below exchange min")
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
				if state.notify:
					base_ccy = settings.symbol.split("/")[0]
					notional_usdt = amount_to_sell * price
					await state.notify(f"فروش انجام شد: {amount_to_sell:.6f} {base_ccy} @ {price:.4f} ≈ {notional_usdt:.2f} USDT")
				if candle_ts is not None:
					state.last_action_candle_ts = candle_ts
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
				msg = f"خرید انجام نشد: کمتر از حداقل صرافی (amount={amount_base_cap}, notional={notional:.4f} USDT)"
				logger.warning("BUY skipped: below exchange min")
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
				if state.notify:
					base_ccy = settings.symbol.split("/")[0]
					await state.notify(f"خرید انجام شد: {amount_base_cap:.6f} {base_ccy} @ {price:.4f} ≈ {amount_quote_cap:.2f} USDT")
				if candle_ts is not None:
					state.last_action_candle_ts = candle_ts
				return {"status": "bought", "order": order, "signal": state.last_signal}
			finally:
				state.order_lock = False
		else:
			return {"status": "no_signal", "signal": state.last_signal}