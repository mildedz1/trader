from __future__ import annotations

import asyncio
from typing import Sequence

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message

from app.config.settings import settings
from app.logging import logger


async def run_bot(stop_event: asyncio.Event) -> None:
    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher()

    admin_ids: Sequence[int] = [int(x) for x in settings.admin_telegram_user_ids.split(",") if x.strip()]

    @dp.message(Command("start"))
    async def on_start(message: Message) -> None:
        await message.answer("LBank trader bot is running. Use /status")

    @dp.message(Command("status"))
    async def on_status(message: Message) -> None:
        await message.answer("OK")

    @dp.message(Command("stop"))
    async def on_stop(message: Message) -> None:
        if message.from_user and message.from_user.id in admin_ids:
            await message.answer("Stopping bot...")
            stop_event.set()
        else:
            await message.answer("Unauthorized")

    async def _runner() -> None:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types(), stop_event=stop_event)

    await _runner()

