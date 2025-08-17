from app.core.config import Settings
from app.strategy.logic import evaluate_ema_rsi, evaluate_bb_breakout


def base_settings():
	return Settings.model_validate({
		"TELEGRAM_TOKEN": "x",
		"ALLOWED_CHAT_IDS": "1",
		"SYMBOL": "ETH/USDT",
		"TIMEFRAME": "1h",
		"MODE": "live",
	})


def test_ema_rsi_runs():
	settings = base_settings()
	closes = [i for i in range(1, 300)]
	res = evaluate_ema_rsi(closes, settings)
	assert isinstance(res.should_long, bool)
	assert isinstance(res.should_exit, bool)


def test_bb_breakout_runs():
	settings = base_settings()
	closes = [i for i in range(1, 300)]
	res = evaluate_bb_breakout(closes, settings)
	assert isinstance(res.should_long, bool)
	assert isinstance(res.should_exit, bool)