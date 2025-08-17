from __future__ import annotations

import asyncio
import json
import os
from typing import Callable, Optional

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message
from loguru import logger

from ..core.config import Settings
from ..core.state import WorkerState


class TelegramWorkerBot:
	def __init__(self, settings: Settings, state: WorkerState):
		self.settings = settings
		self.state = state
		self.bot = Bot(token=settings.telegram_token)
		self.dp = Dispatcher()

		self.dp.message.register(self.cmd_start, Command(commands=["start"]))
		self.dp.message.register(self.cmd_status, Command(commands=["status"]))
		self.dp.message.register(self.cmd_pause, Command(commands=["pause"]))
		self.dp.message.register(self.cmd_resume, Command(commands=["resume"]))
		self.dp.message.register(self.cmd_config, Command(commands=["config"]))
		self.dp.message.register(self.cmd_logs, Command(commands=["logs"]))

	def is_allowed(self, message: Message) -> bool:
		user_id = message.from_user.id if message.from_user else 0
		return int(user_id) in set(self.settings.allowed_chat_ids)

	async def cmd_start(self, message: Message) -> None:
		if not self.is_allowed(message):
			return
		intro = (
			"LBank Spot Trader Worker\n"
			"Use keys with Trade+Read only and WITHDRAWALS DISABLED.\n\n"
			f"Mode: {self.settings.mode}\n"
			f"Symbol: {self.settings.symbol} Timeframe: {self.settings.timeframe}\n"
			f"EMA: {self.settings.ema_fast}/{self.settings.ema_slow} RSI: {self.settings.rsi_period} entry={self.settings.rsi_entry} exit={self.settings.rsi_exit}\n"
			f"Tick: {self.settings.tick_interval_sec}s Risk: {self.settings.risk_position_mode}={self.settings.risk_position_size}\n"
			f"MaxDailyLoss: {self.settings.max_daily_loss_pct}% ResetHourUTC: {self.settings.reset_hour_utc}\n"
		)
		await message.answer(intro)

	async def cmd_status(self, message: Message) -> None:
		if not self.is_allowed(message):
			return
		pos = self.state.position
		status = (
			f"Paused: {self.state.is_paused}\n"
			f"Last signal: {self.state.last_signal}\n"
			f"Position: long={pos.is_long} qty={pos.quantity:.6f} entry={pos.entry_price:.2f}\n"
			f"DailyPnL: {self.state.daily_pnl:.2f}\n"
		)
		await message.answer(status)

	async def cmd_pause(self, message: Message) -> None:
		if not self.is_allowed(message):
			return
		self.state.is_paused = True
		await message.answer("Paused trading.")

	async def cmd_resume(self, message: Message) -> None:
		if not self.is_allowed(message):
			return
		self.state.is_paused = False
		await message.answer("Resumed trading.")

	async def cmd_config(self, message: Message) -> None:
		if not self.is_allowed(message):
			return
		# Allow updating some runtime params via JSON payload after /config
		parts = message.text.split(maxsplit=1) if message.text else []
		if len(parts) == 2:
			try:
				payload = json.loads(parts[1])
				self.settings.persist_overrides(payload)
				await message.answer("Config updated and persisted. Restart container to fully apply.")
				return
			except Exception as exc:  # noqa: BLE001
				await message.answer(f"Invalid JSON: {exc}")
				return
		cfg = {
			"SYMBOL": self.settings.symbol,
			"TIMEFRAME": self.settings.timeframe,
			"EMA_FAST": self.settings.ema_fast,
			"EMA_SLOW": self.settings.ema_slow,
			"RSI_PERIOD": self.settings.rsi_period,
			"RSI_ENTRY": self.settings.rsi_entry,
			"RSI_EXIT": self.settings.rsi_exit,
			"TICK_INTERVAL_SEC": self.settings.tick_interval_sec,
			"RISK_POSITION_MODE": self.settings.risk_position_mode,
			"RISK_POSITION_SIZE": self.settings.risk_position_size,
			"MAX_DAILY_LOSS_PCT": self.settings.max_daily_loss_pct,
			"RESET_HOUR_UTC": self.settings.reset_hour_utc,
			"MODE": self.settings.mode,
		}
		await message.answer("Current config as JSON (send /config {json} to update):\n" + json.dumps(cfg, indent=2))

	async def cmd_logs(self, message: Message) -> None:
		if not self.is_allowed(message):
			return
		log_path = self.settings.log_path
		try:
			if not os.path.exists(log_path):
				await message.answer("No logs yet.")
				return
			with open(log_path, "r", encoding="utf-8") as f:
				lines = f.readlines()[-50:]
			await message.answer("".join(lines) or "(empty)")
		except Exception as exc:  # noqa: BLE001
			await message.answer(f"Failed to read logs: {exc}")

	async def run(self) -> None:
		logger.info("Starting Telegram bot")
		await self.dp.start_polling(self.bot)