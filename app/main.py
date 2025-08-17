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

		async def balance_provider() -> str:
			bal = await self.adapter.fetch_balance()
			free = bal.get("free") or bal.get("total") or {}
			base_ccy, quote_ccy = self.settings.symbol.split("/")
			base = float(free.get(base_ccy, 0.0))
			usdt = float(free.get(quote_ccy, 0.0))
			ticker = await self.adapter.fetch_ticker(self.settings.symbol)
			price = float(ticker.get("last") or ticker.get("close") or 0.0)
			equity = usdt + base * price
			ready_buy = usdt >= 1.0
			ready_sell = base * price >= 0.01  # arbitrary tiny threshold
			lines = [
				f"موجودی {quote_ccy}: {usdt:.4f}",
				f"موجودی {base_ccy}: {base:.8f}",
				f"قیمت {self.settings.symbol}: {price:.4f}",
				f"اکویتی تقریبی: {equity:.4f} USDT",
				f"آمادگی خرید (≤ 1 USDT): {'بله' if ready_buy else 'خیر'}",
				f"آمادگی فروش (≤ 1 USDT معادل): {'بله' if ready_sell else 'خیر'}",
			]
			return "\n".join(lines)

		self.state.balance_provider = balance_provider

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
				required_n = max(200, int(self.settings.ema_slow) + 1, int(self.settings.macd_slow) + int(self.settings.macd_signal) + 1)
				ohlcv = await self.fetch_ohlcv(limit=max(required_n + 5, 220))
				if not ohlcv or len(ohlcv) < required_n:
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

	try:
		bot = TelegramWorkerBot(settings, worker.state)
	except Exception:
		await worker.shutdown()
		raise

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