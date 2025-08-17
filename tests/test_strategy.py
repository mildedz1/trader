from app.core.config import Settings
from app.strategy.logic import evaluate_macd_zero_trend


def base_settings():
	return Settings.model_validate({
		"TELEGRAM_TOKEN": "x",
		"ALLOWED_CHAT_IDS": "1",
		"SYMBOL": "ETH/USDT",
		"TIMEFRAME": "30m",
		"MODE": "live",
	})


def test_macd_zero_trend_runs():
	settings = base_settings()
	closes = [i for i in range(1, 300)]
	res = evaluate_macd_zero_trend(closes, settings)
	assert isinstance(res.should_long, bool)
	assert isinstance(res.should_exit, bool)