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