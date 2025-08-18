from __future__ import annotations

import asyncio
from typing import Sequence

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config.settings import settings
from app.logging import logger
from app.lbank_spot.time_source import fetch_spot_server_time_ms
from app.time_sync import TimeSynchronizer
from app.lbank_spot import LBankSpotClient


class AppState:
    def __init__(self) -> None:
        self.mode: str = "paper"  # paper/dry-run/live
        self.spot_time = TimeSynchronizer(fetch_server_ms=fetch_spot_server_time_ms)
        self.spot_client: LBankSpotClient | None = None
        self._bg_tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        await self.spot_time.refresh()
        if settings.lbank_spot_api_key and settings.lbank_spot_secret_key:
            self.spot_client = LBankSpotClient(
                api_key=settings.lbank_spot_api_key,
                secret_key=settings.lbank_spot_secret_key,
                time_sync=self.spot_time,
            )
            await self.spot_client.open()

        async def _time_refresher() -> None:
            while True:
                try:
                    await self.spot_time.refresh()
                except Exception as exc:
                    logger.error("time.refresh.error", error=str(exc))
                await asyncio.sleep(30)

        self._bg_tasks.append(asyncio.create_task(_time_refresher()))

    async def stop(self) -> None:
        for t in self._bg_tasks:
            t.cancel()
        if self.spot_client:
            await self.spot_client.close()


def admin_kb(state: AppState) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text=f"Mode: {state.mode}", callback_data="mode:menu")
    kb.button(text="Spot Balance", callback_data="spot:balance")
    kb.button(text="Time Drift", callback_data="time:drift")
    kb.adjust(1)
    return kb


def mode_kb(current: str) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for m in ("paper", "dry-run", "live"):
        prefix = "✅ " if m == current else ""
        kb.button(text=f"{prefix}{m}", callback_data=f"mode:set:{m}")
    kb.button(text="⬅️ Back", callback_data="admin:home")
    kb.adjust(3, 1)
    return kb


async def run_bot(stop_event: asyncio.Event) -> None:
    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher()

    state = AppState()
    await state.start()

    admin_ids: Sequence[int] = [int(x) for x in settings.admin_telegram_user_ids.split(",") if x.strip()]

    def is_admin(user_id: int | None) -> bool:
        return bool(user_id and user_id in admin_ids)

    @dp.message(Command("start"))
    async def on_start(message: Message) -> None:
        await message.answer("LBank trader bot is running. Use /admin")

    @dp.message(Command("status"))
    async def on_status(message: Message) -> None:
        await message.answer("OK")

    @dp.message(Command("admin"))
    async def on_admin(message: Message) -> None:
        if not is_admin(message.from_user.id if message.from_user else None):
            await message.answer("Unauthorized")
            return
        await message.answer("Admin Dashboard", reply_markup=admin_kb(state).as_markup())

    @dp.message(Command("stop"))
    async def on_stop(message: Message) -> None:
        if is_admin(message.from_user.id if message.from_user else None):
            await message.answer("Stopping bot...")
            stop_event.set()
        else:
            await message.answer("Unauthorized")

    @dp.callback_query(F.data == "admin:home")
    async def cb_admin_home(cb: CallbackQuery) -> None:
        await cb.message.edit_text("Admin Dashboard", reply_markup=admin_kb(state).as_markup())
        await cb.answer()

    @dp.callback_query(F.data == "mode:menu")
    async def cb_mode_menu(cb: CallbackQuery) -> None:
        await cb.message.edit_text("Select mode", reply_markup=mode_kb(state.mode).as_markup())
        await cb.answer()

    @dp.callback_query(F.data.startswith("mode:set:"))
    async def cb_mode_set(cb: CallbackQuery) -> None:
        mode = cb.data.split(":", 2)[2]
        state.mode = mode
        await cb.message.edit_text("Mode updated.", reply_markup=admin_kb(state).as_markup())
        await cb.answer("Mode set to %s" % mode)

    @dp.callback_query(F.data == "time:drift")
    async def cb_time_drift(cb: CallbackQuery) -> None:
        drift = abs(state.spot_time._offset_ms)
        await cb.answer()
        await cb.message.edit_text(f"Time drift: {drift} ms", reply_markup=admin_kb(state).as_markup())

    @dp.callback_query(F.data == "spot:balance")
    async def cb_spot_balance(cb: CallbackQuery) -> None:
        if not state.spot_client:
            await cb.answer()
            await cb.message.edit_text("Spot API keys are missing.", reply_markup=admin_kb(state).as_markup())
            return
        try:
            data = await state.spot_client.user_info_account()
            # Expected format per LBank: { data: { balances: [{asset, free, locked}, ...] } }
            balances = []
            if isinstance(data, dict):
                d = data.get("data") or {}
                balances = d.get("balances") or []
            lines = ["Asset  Free  Locked"]
            shown = 0
            for b in balances:
                free = b.get("free")
                locked = b.get("locked")
                asset = b.get("asset")
                if (free and float(free) > 0) or (locked and float(locked) > 0):
                    lines.append(f"{asset}  {free}  {locked}")
                    shown += 1
                    if shown >= 30:
                        break
            text = "\n".join(lines) if shown else "No non-zero balances."
            await cb.message.edit_text(text, reply_markup=admin_kb(state).as_markup())
        except Exception as exc:
            await cb.message.edit_text(f"Balance error: {exc}", reply_markup=admin_kb(state).as_markup())
        finally:
            await cb.answer()

    async def _runner() -> None:
        try:
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types(), stop_event=stop_event)
        finally:
            await state.stop()

    await _runner()

