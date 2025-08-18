from __future__ import annotations

from typing import List, Tuple


def ema(values: List[float], period: int) -> List[float]:
	if period <= 1 or not values:
		return list(values)
	alpha = 2.0 / (period + 1)
	res: List[float] = [float(values[0])]
	for v in values[1:]:
		res.append(alpha * float(v) + (1 - alpha) * res[-1])
	return res


def rsi(values: List[float], period: int) -> List[float]:
	if period <= 0:
		return [0.0 for _ in values]
	gains: List[float] = [0.0]
	losses: List[float] = [0.0]
	for i in range(1, len(values)):
		delta = float(values[i]) - float(values[i - 1])
		gains.append(max(delta, 0.0))
		losses.append(max(-delta, 0.0))
	avg_gain = sum(gains[:period]) / max(1, period)
	avg_loss = sum(losses[:period]) / max(1, period)
	res: List[float] = [0.0] * len(values)
	for i in range(period, len(values)):
		if i > period:
			avg_gain = (avg_gain * (period - 1) + gains[i]) / period
			avg_loss = (avg_loss * (period - 1) + losses[i]) / period
		rs = float('inf') if avg_loss == 0 else avg_gain / avg_loss
		res[i] = 100.0 - (100.0 / (1.0 + rs))
	return res


def macd(values: List[float], fast: int, slow: int, signal: int) -> Tuple[List[float], List[float], List[float]]:
	fast_ema = ema(values, fast)
	slow_ema = ema(values, slow)
	line = [f - s for f, s in zip(fast_ema, slow_ema)]
	signal_line = ema(line, signal)
	hist = [l - s for l, s in zip(line, signal_line)]
	return line, signal_line, hist