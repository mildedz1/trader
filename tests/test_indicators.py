from app.strategy.indicators import ema, rsi, macd


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


def test_macd_smoke():
	values = [i for i in range(1, 300)]
	m, s, h = macd(values, 12, 26, 9)
	assert len(m) == len(values)
	assert len(s) == len(values)
	assert len(h) == len(values)