from __future__ import annotations

import asyncio
from typing import Optional

from .core import Settings
from .core.state import WorkerState
from .exchange.lbank_spot import LBankSpot
from .exchange.lbank_futures import LBankFutures
from .bot.telegram_bot import TelegramWorkerBot
from .strategy.logic import evaluate_macd_zero_trend


async def run_worker(settings: Settings, state: WorkerState) -> None:
	# pick exchange
	if settings.trade_mode == "futures":
		ex = LBankFutures()
		sym = settings.futures_symbol
		tf = settings.futures_timeframe
	else:
		ex = LBankSpot()
		sym = settings.symbol
		tf = settings.timeframe
	await ex.connect()
	# bind actions
	async def diagnose() -> str:
		try:
			o = await ex.fetch_ohlcv(sym, tf, 5)
			t_ok = bool(o)
			t = await ex.fetch_ticker(sym)
			p = float(t.get("last") or t.get("close") or 0.0)
			b = await ex.fetch_balance()
			return f"OHLCV={t_ok} Ticker={p>0} Balance={isinstance(b, dict)}"
		except Exception as exc:
			return f"diag error: {exc}"
	state.diagnose = diagnose
	async def force_long() -> str:
		try:
			t = await ex.fetch_ticker(sym)
			p = float(t.get("last") or t.get("close") or 0.0)
			# simple 1 USDT
			order = await ex.create_market_buy_order(sym, 1.0)
			return f"LONG ok @~{p:.4f}: {order}"
		except Exception as exc:
			return f"LONG failed: {exc}"
	state.manual_force_long = force_long
	async def force_short() -> str:
		try:
			# minimal: market sell 0.001 base
			order = await ex.create_market_sell_order(sym, 0.001)
			return f"SHORT ok: {order}"
		except Exception as exc:
			return f"SHORT failed: {exc}"
	state.manual_force_short = force_short
	# simple loop
	while True:
		try:
			ohlcv = await ex.fetch_ohlcv(sym, tf, 300)
			closes = [float(x[4]) for x in ohlcv] if ohlcv else []
			if closes:
				res = evaluate_macd_zero_trend(closes, settings)
				state.last_signal = f"long={res.should_long} exit={res.should_exit}"
		except Exception:
			pass
		await asyncio.sleep(float(settings.tick_interval_sec))


async def main_async() -> None:
	settings = Settings.load()
	state = WorkerState()
	bot = TelegramWorkerBot(settings, state)
	worker_task = asyncio.create_task(run_worker(settings, state))
	bot_task = asyncio.create_task(bot.run())
	await asyncio.gather(worker_task, bot_task)


def main() -> None:
	asyncio.run(main_async())