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


def crossed_up(series: List[float], threshold: float) -> bool:
	if len(series) < 2:
		return False
	return series[-2] < threshold and series[-1] >= threshold


def sma(values: List[float], period: int) -> List[float]:
	if period <= 0:
		raise ValueError("SMA period must be > 0")
	res: List[float] = []
	for i in range(len(values)):
		if i + 1 < period:
			res.append(0.0)
			continue
		window = values[i + 1 - period : i + 1]
		res.append(sum(window) / period)
	return res


def stddev(values: List[float], period: int) -> List[float]:
	if period <= 0:
		raise ValueError("STD period must be > 0")
	res: List[float] = []
	for i in range(len(values)):
		if i + 1 < period:
			res.append(0.0)
			continue
		window = values[i + 1 - period : i + 1]
		mean = sum(window) / period
		var = sum((x - mean) ** 2 for x in window) / period
		res.append(var ** 0.5)
	return res


def bollinger_bands(closes: List[float], period: int, std_mult: float) -> Tuple[List[float], List[float], List[float]]:
	basis = sma(closes, period)
	sd = stddev(closes, period)
	upper: List[float] = []
	lower: List[float] = []
	for i in range(len(closes)):
		upper.append(basis[i] + std_mult * sd[i])
		lower.append(basis[i] - std_mult * sd[i])
	return upper, basis, lower


def bb_bandwidth(upper: List[float], basis: List[float], lower: List[float]) -> List[float]:
	bw: List[float] = []
	for u, b, l in zip(upper, basis, lower):
		if b == 0:
			bw.append(0.0)
		else:
			bw.append((u - l) / b)
	return bw


def percentile(values: List[float], p: float) -> float:
	if not values:
		return 0.0
	vals = sorted(values)
	k = max(0, min(len(vals) - 1, int(round((p / 100.0) * (len(vals) - 1)))))
	return vals[k]