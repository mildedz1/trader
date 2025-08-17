from __future__ import annotations

import asyncio
import json
import os
from typing import Callable, Optional

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
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
			"🤖 ربات معامله‌گر LBank Spot (فقط حالت زنده)",
			"کلید API با مجوز Trade + Read بسازید و Withdrawals را غیرفعال نگه دارید.",
			"",
			f"• نماد: {self.settings.symbol}",
			f"• تایم‌فریم: {self.settings.timeframe}",
			"• استراتژی: macd_zero_trend",
			f"• ریسک: {self.settings.risk_position_size} USDT (سقف هر سفارش 1 USDT)",
			f"• Trend EMA: {self.settings.ema_fast}/{self.settings.ema_slow}",
			f"• MACD: fast={self.settings.macd_fast}, slow={self.settings.macd_slow}, signal={self.settings.macd_signal}",
			f"• RSI Confirm: {'فعال' if self.settings.rsi_confirm else 'غیرفعال'} (سطح={self.settings.rsi_confirm_level})",
			f"• حد باخت روزانه: {self.settings.max_daily_loss_pct}% | ریست (UTC): {self.settings.reset_hour_utc}",
		]
		await message.answer("\n".join(intro_lines), reply_markup=self.main_menu())

	def _fmt_float(self, v: float, n: int) -> str:
		return f"{v:.{n}f}"

	async def cmd_status(self, message: Message) -> None:
		if not self.is_allowed(message):
			return
		await message.answer(await self._build_status_text(), reply_markup=self.main_menu())

	async def _build_status_text(self) -> str:
		pos = self.state.position
		paused = "بله" if self.state.is_paused else "خیر"
		cooldown = f" (Cooldown: {self.state.cooldown_candles_remaining})" if self.state.cooldown_candles_remaining > 0 else ""
		lines = [
			"📊 وضعیت کارگر",
			f"• توقف: {paused}{cooldown}",
			"• استراتژی: macd_zero_trend",
			f"• آخرین کندل: {self.state.last_candle_ts or '-'}",
			"",
			"پوزیشن:",
			f"  - لانگ: {pos.is_long}",
			f"  - مقدار: {self._fmt_float(pos.quantity, 6)} {self.settings.symbol.split('/')[0]}",
			f"  - قیمت ورود: {self._fmt_float(pos.entry_price, 4)}",
			"",
			"سیگنال اخیر:",
			f"  - تصمیم ورود (BUY): {self.state.last_decision_long}",
			f"  - تصمیم خروج (SELL): {self.state.last_decision_exit}",
		]
		metrics = self.state.last_metrics or {}
		ema_fast = metrics.get("ema_fast")
		ema_slow = metrics.get("ema_slow")
		h_prev = metrics.get("macd_hist_prev")
		h_now = metrics.get("macd_hist_now")
		trend_ok = bool(metrics.get("trend_ok", 0.0))
		zero_up = bool(metrics.get("zero_up", 0.0))
		zero_down = bool(metrics.get("zero_down", 0.0))
		rsi_now = metrics.get("rsi_now")
		vals = []
		if ema_fast is not None and ema_slow is not None:
			vals.append(f"  - EMA_fast/slow: {self._fmt_float(ema_fast,2)} / {self._fmt_float(ema_slow,2)}")
		if h_prev is not None and h_now is not None:
			vals.append(f"  - MACD Hist: prev={self._fmt_float(h_prev,4)} now={self._fmt_float(h_now,4)}")
		if vals:
			lines += vals
		# Entry condition summary
		entry_ok = trend_ok and zero_up and (True if not self.settings.rsi_confirm else (rsi_now is not None and rsi_now >= self.settings.rsi_confirm_level))
		lines += [
			"",
			"شرایط ورود (BUY):",
			f"  - روند (EMA50>EMA200): {'بله' if trend_ok else 'خیر'}",
			f"  - MACD zero-cross up: {'بله' if zero_up else 'خیر'}",
		]
		if self.settings.rsi_confirm:
			lines.append(f"  - RSI ≥ {self.settings.rsi_confirm_level}: {'بله' if (rsi_now is not None and rsi_now >= self.settings.rsi_confirm_level) else 'خیر'}")
		lines.append(f"  => نتیجه: {'آماده ورود' if entry_ok else 'ورود غیرفعال'}")
		lines += ["", f"سود/زیان روزانه: {self._fmt_float(self.state.daily_pnl,4)} USDT"]
		return "\n".join(lines)

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
				await message.answer("تنظیمات به‌روزرسانی و ذخیره شد.", reply_markup=self.main_menu())
				return
			except Exception as exc:  # noqa: BLE001
				await message.answer(f"فرمت JSON نامعتبر است: {exc}", reply_markup=self.main_menu())
				return
		cfg = {
			"SYMBOL": self.settings.symbol,
			"TIMEFRAME": self.settings.timeframe,
			"EMA_FAST": self.settings.ema_fast,
			"EMA_SLOW": self.settings.ema_slow,
			"MACD_FAST": self.settings.macd_fast,
			"MACD_SLOW": self.settings.macd_slow,
			"MACD_SIGNAL": self.settings.macd_signal,
			"RSI_CONFIRM": self.settings.rsi_confirm,
			"RSI_CONFIRM_LEVEL": self.settings.rsi_confirm_level,
			"RISK_POSITION_SIZE": self.settings.risk_position_size,
			"MAX_DAILY_LOSS_PCT": self.settings.max_daily_loss_pct,
			"RESET_HOUR_UTC": self.settings.reset_hour_utc,
		}
		help_text = """به‌روزرسانی تنظیمات:
/config {JSON}

نمونه:
/config {\"TIMEFRAME\":\"30m\",\"EMA_FAST\":50,\"EMA_SLOW\":200,\"MACD_FAST\":12,\"MACD_SLOW\":26,\"MACD_SIGNAL\":9,\"RSI_CONFIRM\":true,\"RSI_CONFIRM_LEVEL\":45}
"""
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