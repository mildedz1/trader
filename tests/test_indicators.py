from app.strategy.indicators import ema, rsi, crossed_up


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