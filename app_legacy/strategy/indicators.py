from __future__ import annotations

from typing import Iterable, List, Tuple


def ema(values: Iterable[float], period: int) -> List[float]:
	values_list = list(values)
	if period <= 0:
		raise ValueError("EMA period must be > 0")
	if len(values_list) == 0:
		return []
	k = 2 / (period + 1)
	emas: List[float] = []
	for i, v in enumerate(values_list):
		if i == 0:
			emas.append(float(v))
		else:
			emas.append(v * k + emas[-1] * (1 - k))
	return emas


def rsi(values: Iterable[float], period: int) -> List[float]:
	values_list = list(values)
	if period <= 0:
		raise ValueError("RSI period must be > 0")
	if len(values_list) < period + 1:
		return [0.0 for _ in values_list]
	gains: List[float] = []
	losses: List[float] = []
	for i in range(1, len(values_list)):
		delta = values_list[i] - values_list[i - 1]
		gains.append(max(delta, 0.0))
		losses.append(max(-delta, 0.0))
	avg_gain = sum(gains[:period]) / period
	avg_loss = sum(losses[:period]) / period
	rsi_values: List[float] = [0.0] * len(values_list)
	if avg_loss == 0:
		rsi_values[period] = 100.0
	else:
		rs = avg_gain / avg_loss
		rsi_values[period] = 100 - (100 / (1 + rs))
	for i in range(period + 1, len(values_list)):
		gain = gains[i - 1]
		loss = losses[i - 1]
		avg_gain = (avg_gain * (period - 1) + gain) / period
		avg_loss = (avg_loss * (period - 1) + loss) / period
		if avg_loss == 0:
			rsi_values[i] = 100.0
		else:
			rs = avg_gain / avg_loss
			rsi_values[i] = 100 - (100 / (1 + rs))
	return rsi_values


def macd(values: Iterable[float], fast: int, slow: int, signal: int) -> Tuple[List[float], List[float], List[float]]:
	closes = list(values)
	if fast <= 0 or slow <= 0 or signal <= 0:
		raise ValueError("MACD periods must be > 0")
	ema_fast = ema(closes, fast)
	ema_slow = ema(closes, slow)
	macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
	signal_line = ema(macd_line, signal)
	hist = [m - s for m, s in zip(macd_line, signal_line)]
	return macd_line, signal_line, hist


def atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> List[float]:
	if period <= 0:
		raise ValueError("ATR period must be > 0")
	tr: List[float] = []
	for i in range(len(closes)):
		if i == 0:
			tr.append(highs[i] - lows[i])
		else:
			hl = highs[i] - lows[i]
			hc = abs(highs[i] - closes[i - 1])
			lc = abs(lows[i] - closes[i - 1])
			tr.append(max(hl, hc, lc))
	atr_vals: List[float] = []
	for i, v in enumerate(tr):
		if i == 0:
			atr_vals.append(v)
		else:
			atr_vals.append((atr_vals[-1] * (period - 1) + v) / period)
	return atr_vals


def supertrend(highs: List[float], lows: List[float], closes: List[float], period: int, multiplier: float) -> Tuple[List[float], List[int]]:
	# Returns (supertrend_line, trend_direction) where trend_direction: 1=Long, -1=Short
	atr_vals = atr(highs, lows, closes, period)
	basic_upper: List[float] = []
	basic_lower: List[float] = []
	for i in range(len(closes)):
		mid = (highs[i] + lows[i]) / 2.0
		basic_upper.append(mid + multiplier * atr_vals[i])
		basic_lower.append(mid - multiplier * atr_vals[i])
	final_upper: List[float] = basic_upper.copy()
	final_lower: List[float] = basic_lower.copy()
	for i in range(1, len(closes)):
		if basic_upper[i] < final_upper[i - 1] or closes[i - 1] > final_upper[i - 1]:
			final_upper[i] = basic_upper[i]
		else:
			final_upper[i] = final_upper[i - 1]
		if basic_lower[i] > final_lower[i - 1] or closes[i - 1] < final_lower[i - 1]:
			final_lower[i] = basic_lower[i]
		else:
			final_lower[i] = final_lower[i - 1]
	super: List[float] = [0.0] * len(closes)
	trend: List[int] = [1] * len(closes)
	for i in range(1, len(closes)):
		if super[i - 1] == final_upper[i - 1] and closes[i] <= final_upper[i]:
			super[i] = final_upper[i]
			trend[i] = -1
		elif super[i - 1] == final_upper[i - 1] and closes[i] > final_upper[i]:
			super[i] = final_lower[i]
			trend[i] = 1
		elif super[i - 1] == final_lower[i - 1] and closes[i] >= final_lower[i]:
			super[i] = final_lower[i]
			trend[i] = 1
		else:
			super[i] = final_upper[i]
			trend[i] = -1
	return super, trend