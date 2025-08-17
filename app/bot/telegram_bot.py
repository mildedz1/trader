from __future__ import annotations

import asyncio
import json
import os
from typing import Callable, Optional

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from loguru import logger

from ..core.config import Settings
from ..core.state import WorkerState


class TelegramWorkerBot:
	def __init__(self, settings: Settings, state: WorkerState):
		self.settings = settings
		self.state = state
		self.bot = Bot(token=settings.telegram_token, parse_mode=ParseMode.MARKDOWN)
		self.dp = Dispatcher()

		self.dp.message.register(self.cmd_start, Command(commands=["start"]))
		self.dp.message.register(self.cmd_status, Command(commands=["status"]))
		self.dp.message.register(self.cmd_pause, Command(commands=["pause"]))
		self.dp.message.register(self.cmd_resume, Command(commands=["resume"]))
		self.dp.message.register(self.cmd_config, Command(commands=["config"]))
		self.dp.message.register(self.cmd_logs, Command(commands=["logs"]))
		self.dp.callback_query.register(self.on_menu_click, F.data.startswith("menu:"))

		# Wire state notifier
		async def _notify(text: str) -> None:
			try:
				for chat_id in self.settings.allowed_chat_ids:
					await self.bot.send_message(chat_id, text)
			except Exception:
				pass
		self.state.notify = _notify

	def is_allowed(self, message: Message) -> bool:
		user_id = message.from_user.id if message.from_user else 0
		return int(user_id) in set(self.settings.allowed_chat_ids)

	def main_menu(self) -> InlineKeyboardMarkup:
		kb = [
			[
				InlineKeyboardButton(text="وضعیت", callback_data="menu:status"),
				InlineKeyboardButton(text="موجودی کیف پول", callback_data="menu:balance"),
			],
			[
				InlineKeyboardButton(text="توقف", callback_data="menu:pause"),
				InlineKeyboardButton(text="ادامه", callback_data="menu:resume"),
			],
			[
				InlineKeyboardButton(text="لاگ‌ها", callback_data="menu:logs"),
				InlineKeyboardButton(text="تنظیمات", callback_data="menu:config"),
			],
		]
		return InlineKeyboardMarkup(inline_keyboard=kb)

	async def cmd_start(self, message: Message) -> None:
		if not self.is_allowed(message):
			return
		intro_lines = [
			"ربات معامله‌گر LBank Spot (فقط حالت زنده)",
			"لطفاً کلیدهای API با مجوز *Trade + Read* بسازید و *Withdrawals* را در صرافی *غیرفعال* نگه دارید.",
			"",
			f"- نماد: {self.settings.symbol}",
			f"- تایم‌فریم: {self.settings.timeframe}",
			f"- استراتژی: {self.settings.strategy_id}",
			f"- ریسک: مقدار ثابت {self.settings.risk_position_size} USDT (سقف سخت 1 USDT هر سفارش)",
			f"- EMA: {self.settings.ema_fast}/{self.settings.ema_slow} | RSI: {self.settings.rsi_period} ورودی={self.settings.rsi_entry} خروج={self.settings.rsi_exit}",
			f"- Bollinger: دوره={self.settings.bb_period} انحراف={self.settings.bb_std} پهنای‌باند pctl={self.settings.bb_bw_pctl} RSI تایید={self.settings.rsi_confirm}",
			f"- حداکثر باخت روزانه: {self.settings.max_daily_loss_pct}% | ساعت ریست (UTC): {self.settings.reset_hour_utc}",
		]
		await message.answer("\n".join(intro_lines), reply_markup=self.main_menu())

	async def cmd_status(self, message: Message) -> None:
		if not self.is_allowed(message):
			return
		await message.answer(await self._build_status_text(), reply_markup=self.main_menu())

	async def _build_status_text(self) -> str:
		pos = self.state.position
		status_lines = [
			f"وضعیت توقف: {'بله' if self.state.is_paused else 'خیر'}",
			f"آخرین سیگنال: {self.state.last_signal}",
			f"پوزیشن: لانگ={pos.is_long} | مقدار={pos.quantity:.6f} | ورود={pos.entry_price:.4f}",
			f"سود/زیان روزانه: {self.state.daily_pnl:.4f} USDT",
		]
		if self.state.cooldown_candles_remaining > 0:
			status_lines.append(f"Cooldown: {self.state.cooldown_candles_remaining} کندل باقی‌مانده")
		return "\n".join(status_lines)

	async def _send_balance(self, chat_id: int) -> None:
		if self.state.balance_provider is None:
			await self.bot.send_message(chat_id, "ارائه‌دهنده موجودی تنظیم نشده است.")
			return
		try:
			text = await self.state.balance_provider()
			await self.bot.send_message(chat_id, text)
		except Exception as exc:
			await self.bot.send_message(chat_id, f"دریافت موجودی ناموفق بود: {exc}")

	async def on_menu_click(self, cq: CallbackQuery) -> None:
		chat_id = cq.from_user.id if cq.from_user else 0
		if int(chat_id) not in set(self.settings.allowed_chat_ids):
			await cq.answer()
			return
		action = cq.data.split(":", 1)[1]
		if action == "status":
			await cq.message.edit_text(await self._build_status_text(), reply_markup=self.main_menu())
		elif action == "balance":
			await self._send_balance(chat_id)
			await cq.answer("موجودی به‌روزرسانی شد.")
		elif action == "pause":
			self.state.is_paused = True
			await cq.message.edit_text("ربات در حالت توقف قرار گرفت.", reply_markup=self.main_menu())
		elif action == "resume":
			self.state.is_paused = False
			await cq.message.edit_text("ربات از سر گرفته شد.", reply_markup=self.main_menu())
		elif action == "logs":
			await self.cmd_logs(cq.message)
			await cq.answer("ارسال شد")
		elif action == "config":
			await self.cmd_config(cq.message)
			await cq.answer()
		else:
			await cq.answer()

	async def cmd_pause(self, message: Message) -> None:
		if not self.is_allowed(message):
			return
		self.state.is_paused = True
		await message.answer("ربات در حالت توقف قرار گرفت.", reply_markup=self.main_menu())

	async def cmd_resume(self, message: Message) -> None:
		if not self.is_allowed(message):
			return
		self.state.is_paused = False
		await message.answer("ربات از سر گرفته شد.", reply_markup=self.main_menu())

	async def cmd_config(self, message: Message) -> None:
		if not self.is_allowed(message):
			return
		parts = message.text.split(maxsplit=1) if message.text else []
		if len(parts) == 2:
			try:
				payload = json.loads(parts[1])
				self.settings.persist_overrides(payload)
				await message.answer("تنظیمات به‌روزرسانی و ذخیره شد. برای تغییر استراتژی: ابتدا /pause سپس /config و در پایان /resume.", reply_markup=self.main_menu())
				return
			except Exception as exc:  # noqa: BLE001
				await message.answer(f"فرمت JSON نامعتبر است: {exc}", reply_markup=self.main_menu())
				return
		cfg = {
			"SYMBOL": self.settings.symbol,
			"TIMEFRAME": self.settings.timeframe,
			"STRATEGY_ID": self.settings.strategy_id,
			"RISK_POSITION_MODE": self.settings.risk_position_mode,
			"RISK_POSITION_SIZE": self.settings.risk_position_size,
			"MAX_DAILY_LOSS_PCT": self.settings.max_daily_loss_pct,
			"RESET_HOUR_UTC": self.settings.reset_hour_utc,
			"EMA_FAST": self.settings.ema_fast,
			"EMA_SLOW": self.settings.ema_slow,
			"RSI_PERIOD": self.settings.rsi_period,
			"RSI_ENTRY": self.settings.rsi_entry,
			"RSI_EXIT": self.settings.rsi_exit,
			"BB_PERIOD": self.settings.bb_period,
			"BB_STD": self.settings.bb_std,
			"BB_BW_LOOKBACK": self.settings.bb_bw_lookback,
			"BB_BW_PCTL": self.settings.bb_bw_pctl,
			"RSI_CONFIRM": self.settings.rsi_confirm,
		}
		help_text = """به‌روزرسانی تنظیمات:
/config {JSON}

نمونه:
/config {\"STRATEGY_ID\":\"bb_breakout\",\"RISK_POSITION_SIZE\":1,\"SYMBOL\":\"ETH/USDT\"}

توجه: برای تغییر استراتژی، بهتر است ابتدا ربات را متوقف (/pause) و سپس پس از تغییر، ادامه دهید (/resume)."""
		await message.answer(help_text, reply_markup=self.main_menu())
		await message.answer("تنظیمات فعلی (JSON):\n" + json.dumps(cfg, indent=2), reply_markup=self.main_menu())

	async def cmd_logs(self, message: Message) -> None:
		if not self.is_allowed(message):
			return
		log_path = self.settings.log_path
		try:
			if not os.path.exists(log_path):
				await message.answer("لاگی موجود نیست.", reply_markup=self.main_menu())
				return
			with open(log_path, "r", encoding="utf-8") as f:
				lines = f.readlines()[-50:]
			await message.answer("آخرین ۵۰ خط لاگ:\n" + ("".join(lines) or "(خالی)"), reply_markup=self.main_menu())
		except Exception as exc:  # noqa: BLE001
			await message.answer(f"خواندن لاگ ناموفق بود: {exc}", reply_markup=self.main_menu())

	async def run(self) -> None:
		logger.info("Starting Telegram bot (FA)")
		await self.dp.start_polling(self.bot)