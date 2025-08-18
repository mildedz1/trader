from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from loguru import logger

from ..core.config import Settings
from ..core.state import WorkerState
from ..exchange_adapter.base import ExchangeAdapter
from .indicators import ema, macd, atr, supertrend


@dataclass
class FuturesPosition:
	is_long: bool = False
	is_short: bool = False
	entry_price: float = 0.0
	size_base: float = 0.0
	sl: float = 0.0
	tp: float = 0.0

	def flat(self) -> bool:
		return not self.is_long and not self.is_short

	def set_long(self, price: float, size: float, sl: float, tp: float) -> None:
		self.is_long = True
		self.is_short = False
		self.entry_price = price
		self.size_base = size
		self.sl = sl
		self.tp = tp

	def set_short(self, price: float, size: float, sl: float, tp: float) -> None:
		self.is_long = False
		self.is_short = True
		self.entry_price = price
		self.size_base = size
		self.sl = sl
		self.tp = tp

	def reset(self) -> None:
		self.is_long = False
		self.is_short = False
		self.entry_price = 0.0
		self.size_base = 0.0
		self.sl = 0.0
		self.tp = 0.0


@dataclass
class FuturesState:
	position: FuturesPosition
	trades_today: int = 0
	last_trade_ts: int | None = None


def compute_sl_tp(entry: float, is_long: bool, atr_value: float, sl_atr_mult: float, tp_rr: float) -> Tuple[float, float]:
	risk = atr_value * sl_atr_mult
	if is_long:
		sl = entry - risk
		tp = entry + risk * tp_rr
	else:
		sl = entry + risk
		tp = entry - risk * tp_rr
	return sl, tp


async def run_tick_futures(adapter: ExchangeAdapter, state: WorkerState, fstate: FuturesState, settings: Settings, ohlcv: List[List[float]], candle_ts: int | None) -> Dict:
	# Extract series
	highs = [float(x[2]) for x in ohlcv]
	lows = [float(x[3]) for x in ohlcv]
	closes = [float(x[4]) for x in ohlcv]
	# Indicators
	ema_fast_series = ema(closes, settings.ema_fast)
	ema_slow_series = ema(closes, settings.ema_slow)
	macd_line, signal_line, hist = macd(closes, settings.macd_fast, settings.macd_slow, settings.macd_signal)
	st_line, st_trend = supertrend(highs, lows, closes, settings.st_supertrend_atr_period, settings.st_supertrend_atr_mult)
	atr14 = atr(highs, lows, closes, 14)

	price = closes[-1]
	st_dir = st_trend[-1]  # 1 long, -1 short
	allow_long = st_dir == 1 and ema_fast_series[-1] > ema_slow_series[-1]
	allow_short = settings.futures_allow_short and st_dir == -1 and ema_fast_series[-1] < ema_slow_series[-1]
	h_prev, h_now = (hist[-2], hist[-1]) if len(hist) >= 2 else (0.0, 0.0)
	zero_up = (h_prev <= 0) and (h_now > 0)
	zero_down = (h_prev >= 0) and (h_now < 0)
	long_trigger = allow_long and zero_up and price >= st_line[-1]
	short_trigger = allow_short and zero_down and price <= st_line[-1]

	state.last_signal = f"futures_scalp_st | allow_long={allow_long} allow_short={allow_short} zero_up={zero_up} zero_down={zero_down}"
	state.last_strategy_id = "futures_scalp_st"
	state.last_metrics = {
		"ema_fast": ema_fast_series[-1],
		"ema_slow": ema_slow_series[-1],
		"st_dir": float(st_dir),
		"st_line": st_line[-1],
		"price": price,
		"allow_long": 1.0 if allow_long else 0.0,
		"allow_short": 1.0 if allow_short else 0.0,
		"macd_hist_prev": h_prev,
		"macd_hist_now": h_now,
		"zero_up": 1.0 if zero_up else 0.0,
		"zero_down": 1.0 if zero_down else 0.0,
		"long_trigger": 1.0 if long_trigger else 0.0,
		"short_trigger": 1.0 if short_trigger else 0.0,
	}
	# inject SL/TP if a position exists
	if not fstate.position.flat():
		state.last_metrics["f_sl"] = fstate.position.sl
		state.last_metrics["f_tp"] = fstate.position.tp
	state.last_decision_long = long_trigger
	state.last_decision_exit = short_trigger if fstate.position.is_long else long_trigger if fstate.position.is_short else False
	state.last_candle_ts = candle_ts

	# Rate limits
	if settings.max_daily_loss_pct and state.reached_daily_loss_limit(settings.max_daily_loss_pct):
		state.is_paused = True
		if state.notify:
			await state.notify("محدودیت ضرر روزانه در فیوچرز فعال شد؛ توقف.")
		return {"status": "paused_loss_limit"}

	if state.cooldown_candles_remaining > 0:
		state.cooldown_candles_remaining -= 1
		return {"status": "cooldown"}

	# Manage exits
	if not fstate.position.flat():
		pos = fstate.position
		# Opposite trigger or trend flip
		exit_signal = False
		if pos.is_long and (zero_down or st_dir == -1 or ema_fast_series[-1] <= ema_slow_series[-1]):
			exit_signal = True
		if pos.is_short and (zero_up or st_dir == 1 or ema_fast_series[-1] >= ema_slow_series[-1]):
			exit_signal = True
		# SL/TP and trailing management on closed candles
		# Compute 1R distance
		if pos.is_long:
			R = max(1e-8, pos.entry_price - pos.sl)
			# Move SL to breakeven after +1R and trail if enabled
			if price >= pos.entry_price + R:
				if pos.sl < pos.entry_price:
					pos.sl = pos.entry_price
				if getattr(settings, 'trail_enable', False):
					trail = atr14[-1] * float(getattr(settings, 'trail_atr_mult', 0.8))
					pos.sl = max(pos.sl, price - trail)
			# SL/TP hit
			if price <= pos.sl or price >= pos.tp:
				exit_signal = True
		else:
			R = max(1e-8, pos.sl - pos.entry_price)
			if price <= pos.entry_price - R:
				if pos.sl > pos.entry_price:
					pos.sl = pos.entry_price
				if getattr(settings, 'trail_enable', False):
					trail = atr14[-1] * float(getattr(settings, 'trail_atr_mult', 0.8))
					pos.sl = min(pos.sl, price + trail)
			# SL/TP hit
			if price >= pos.sl or price <= pos.tp:
				exit_signal = True
		if exit_signal:
			if state.order_lock:
				return {"status": "locked"}
			state.order_lock = True
			try:
				amt = pos.size_base
				if amt > 0:
					order = await adapter.create_market_buy_order(settings.futures_symbol if hasattr(settings, 'futures_symbol') else settings.symbol, amt) if pos.is_short else await adapter.create_market_sell_order(settings.futures_symbol if hasattr(settings, 'futures_symbol') else settings.symbol, amt)
					pos.reset()
					state.cooldown_candles_remaining = max(0, int(settings.cooldown_candles_after_exit))
					logger.info(f"FUTURES exit: {order}")
					if state.notify:
						await state.notify("خروج فیوچرز (SL/TP/سیگنال) انجام شد")
					return {"status": "futures_exit", "order": order}
			finally:
				state.order_lock = False
			return {"status": "holding"}
		return {"status": "holding"}

	# Entries
	if fstate.trades_today >= int(getattr(settings, 'max_trades_per_day', 999999)):
		return {"status": "max_trades_reached"}
	if long_trigger or short_trigger:
		if state.order_lock:
			return {"status": "locked"}
		state.order_lock = True
		try:
			# Sizing: prefer explicit FUTURES_MARGIN_USDT if provided
			bal = await adapter.fetch_balance()
			usdt = float((bal.get("free") or {}).get("USDT", 0.0))
			if getattr(settings, 'futures_margin_usdt', None):
				margin_usdt = min(float(settings.futures_margin_usdt or 0.0), usdt)
			else:
				margin_usdt = usdt if settings.use_full_balance else usdt * 0.2
			# leverage effect: base size = (margin * leverage) / price
			base_size = (margin_usdt * float(settings.futures_leverage)) / max(price, 1e-8)
			if base_size <= 0:
				return {"status": "insufficient_margin"}
			# SL/TP
			sl, tp = compute_sl_tp(price, long_trigger, atr14[-1], settings.sl_atr_mult, settings.tp_rr)
			# Place market entry
			if long_trigger:
				order = await adapter.create_market_buy_order(settings.futures_symbol if hasattr(settings, 'futures_symbol') else settings.symbol, margin_usdt)
				fstate.position.set_long(price, base_size, sl, tp)
			else:
				# For short, we simulate by selling base; in real futures, side param required; placeholder
				order = await adapter.create_market_sell_order(settings.futures_symbol if hasattr(settings, 'futures_symbol') else settings.symbol, base_size)
				fstate.position.set_short(price, base_size, sl, tp)
			fstate.trades_today += 1
			logger.info(f"FUTURES entry: {order}")
			if state.notify:
				await state.notify(f"ورود فیوچرز {'لانگ' if long_trigger else 'شورت'} انجام شد @ {price:.4f}")
			return {"status": "futures_entry", "order": order}
		finally:
			state.order_lock = False
	return {"status": "no_signal"}