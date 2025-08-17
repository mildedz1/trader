from app.strategy.indicators import ema, rsi, crossed_up, bollinger_bands, bb_bandwidth, percentile


def test_ema_basic():
	values = [1, 2, 3, 4, 5]
	res = ema(values, 3)
	assert len(res) == len(values)
	assert res[0] == 1
	assert res[-1] > res[-2]


def test_rsi_bounds():
	values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]
	res = rsi(values, 14)
	assert len(res) == len(values)
	assert 0 <= res[-1] <= 100


def test_crossed_up():
	series = [25, 29, 31]
	assert crossed_up(series, 30) is True
	series = [35, 29, 29.5]
	assert crossed_up(series, 30) is False


def test_bollinger_helpers():
	closes = [i for i in range(1, 250)]
	upper, basis, lower = bollinger_bands(closes, 20, 2.0)
	bw = bb_bandwidth(upper, basis, lower)
	assert len(upper) == len(closes)
	assert len(bw) == len(closes)
	p20 = percentile(bw[-200:], 20)
	assert p20 >= 0