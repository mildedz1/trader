from __future__ import annotations

import asyncio
import signal
from typing import List

from loguru import logger

from .core.config import Settings
from .core.logging import setup_logging
from .core.state import WorkerState
from .exchange_adapter.ccxt_lbank import CcxtLBankAdapter
from .strategy.logic import run_tick
import ccxt.async_support as ccxt  # keep import for runtime


class Worker:
	def __init__(self, settings: Settings):
		self.settings = settings
		self.state = WorkerState()
		self._shutdown = asyncio.Event()
		self.adapter = None

	async def startup(self) -> None:
		logger.info("Use LBank API keys with Trade+Read only and Withdrawals disabled.")
		if not self.settings.lbank_api_key or not self.settings.lbank_api_secret:
			raise SystemExit("LBANK_API_KEY and LBANK_API_SECRET are required (live-only mode)")
		self.adapter = CcxtLBankAdapter(self.settings.lbank_api_key, self.settings.lbank_api_secret)
		await self.adapter.connect()
		logger.info("Connected to exchange adapter")

	async def fetch_ohlcv(self, limit: int = 300):
		client = ccxt.lbank({"enableRateLimit": True})
		try:
			await client.load_markets()
			ohlcv = await client.fetch_ohlcv(self.settings.symbol, timeframe=self.settings.timeframe, limit=limit)
			return ohlcv
		finally:
			try:
				await client.close()
			except Exception:
				pass

	async def loop(self) -> None:
		interval = float(self.settings.tick_interval_sec)
		while not self._shutdown.is_set():
			try:
				ohlcv = await self.fetch_ohlcv(limit=max(self.settings.ema_slow + 5, 250))
				if not ohlcv or len(ohlcv) < max(self.settings.ema_slow + 1, self.settings.rsi_period + 1):
					await asyncio.sleep(interval)
					continue
				closes = [float(c[4]) for c in ohlcv]
				last_closed_ts = int(ohlcv[-1][0])
				await run_tick(self.adapter, self.state, self.settings, closes, candle_ts=last_closed_ts)
			except Exception as exc:  # noqa: BLE001
				logger.exception(f"Worker tick error: {exc}")
			await asyncio.sleep(interval)

	async def shutdown(self) -> None:
		self._shutdown.set()
		try:
			if self.adapter:
				await self.adapter.close()
		except Exception:
			pass


async def main_async() -> None:
	settings = Settings.load()
	effective_log = setup_logging(settings.log_path)
	logger.info(f"Logging to {effective_log}")
	worker = Worker(settings)
	await worker.startup()

	# Telegram bot
	from .bot.telegram_bot import TelegramWorkerBot

	bot = TelegramWorkerBot(settings, worker.state)

	loop_task = asyncio.create_task(worker.loop())
	bot_task = asyncio.create_task(bot.run())

	stop_event = asyncio.Event()

	def _handle_signal():
		logger.info("Shutdown signal received")
		stop_event.set()

	for sig in [signal.SIGINT, signal.SIGTERM]:
		try:
			asyncio.get_running_loop().add_signal_handler(sig, _handle_signal)
		except NotImplementedError:
			pass

	await stop_event.wait()
	await worker.shutdown()
	for task in [loop_task, bot_task]:
		if not task.done():
			task.cancel()
			try:
				await task
			except asyncio.CancelledError:
				pass


def main() -> None:
	asyncio.run(main_async())


if __name__ == "__main__":
	main()