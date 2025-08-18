from __future__ import annotations

import asyncio
from typing import Optional

from .core import Settings
from .core.state import WorkerState
from .exchange.lbank_spot import LBankSpot
from .exchange.lbank_futures import LBankFutures
from .bot.telegram_bot import TelegramWorkerBot


async def main_async() -> None:
	settings = Settings.model_validate({
		"TELEGRAM_TOKEN": Settings.__fields__["telegram_token"].alias,  # placeholder; load from env in real app
		"ALLOWED_CHAT_IDS": "1",
		"SYMBOL": "ETH/USDT",
		"TIMEFRAME": "30m",
		"MODE": "live",
	})
	state = WorkerState()
	# Minimal: spin only bot in this scaffold
	bot = TelegramWorkerBot(settings, state)
	await bot.run()


def main() -> None:
	asyncio.run(main_async())