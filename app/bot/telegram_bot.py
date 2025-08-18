from __future__ import annotations

import asyncio
import json
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery

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
		self.dp.callback_query.register(self.on_menu_click, F.data.startswith("menu:"))

	def menu(self) -> InlineKeyboardMarkup:
		kb = [
			[
				InlineKeyboardButton(text="وضعیت", callback_data="menu:status"),
				InlineKeyboardButton(text="عیب‌یابی", callback_data="menu:diagnose"),
			],
			[
				InlineKeyboardButton(text="ورود فوری لانگ", callback_data="menu:force_long"),
				InlineKeyboardButton(text="ورود فوری شورت", callback_data="menu:force_short"),
			],
		]
		return InlineKeyboardMarkup(inline_keyboard=kb)

	async def cmd_start(self, message: Message) -> None:
		await message.answer("ربات آماده است.", reply_markup=self.menu())

	async def cmd_status(self, message: Message) -> None:
		await message.answer("OK", reply_markup=self.menu())

	async def cmd_pause(self, message: Message) -> None:
		self.state.is_paused = True
		await message.answer("توقف شد.", reply_markup=self.menu())

	async def cmd_resume(self, message: Message) -> None:
		self.state.is_paused = False
		await message.answer("ادامه.", reply_markup=self.menu())

	async def cmd_config(self, message: Message) -> None:
		parts = message.text.split(maxsplit=1) if message.text else []
		if len(parts) == 2:
			try:
				payload = json.loads(parts[1])
				from ..core.config import Settings as _S
				# Persist naive: not included in this minimal scaffold
				await message.answer("ثبت شد.", reply_markup=self.menu())
				return
			except Exception as exc:
				await message.answer(f"JSON نامعتبر: {exc}", reply_markup=self.menu())
				return
		await message.answer("/config {JSON}", reply_markup=self.menu())

	async def on_menu_click(self, cq: CallbackQuery) -> None:
		a = cq.data.split(":", 1)[1]
		if a == "status":
			await cq.message.edit_text("OK", reply_markup=self.menu())
		elif a == "diagnose":
			if self.state.diagnose:
				text = await self.state.diagnose()
				await cq.message.answer(text)
			await cq.answer()
		elif a == "force_long":
			if self.state.manual_force_long:
				text = await self.state.manual_force_long()
				await cq.message.answer(text)
			await cq.answer()
		elif a == "force_short":
			if self.state.manual_force_short:
				text = await self.state.manual_force_short()
				await cq.message.answer(text)
			await cq.answer()
		else:
			await cq.answer()

	async def run(self) -> None:
		await self.dp.start_polling(self.bot)