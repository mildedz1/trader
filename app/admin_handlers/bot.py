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
from app.lbank_perp.time_source import fetch_perp_server_time_ms
from app.time_sync import TimeSynchronizer
from app.lbank_spot import LBankSpotClient
from app.lbank_perp import LBankPerpClient
from app.strategy_engine.engine import StrategyEngine


class AppState:
    def __init__(self) -> None:
        self.mode: str = "signal"  # signal/live
        self.spot_time = TimeSynchronizer(fetch_server_ms=fetch_spot_server_time_ms)
        self.spot_client: LBankSpotClient | None = None
        self.perp_time = TimeSynchronizer(fetch_server_ms=fetch_perp_server_time_ms)
        self.perp_client: LBankPerpClient | None = None
        self._bg_tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        await self.spot_time.refresh()
        await self.perp_time.refresh()
        if settings.lbank_spot_api_key and settings.lbank_spot_secret_key:
            self.spot_client = LBankSpotClient(
                api_key=settings.lbank_spot_api_key,
                secret_key=settings.lbank_spot_secret_key,
                time_sync=self.spot_time,
            )
            await self.spot_client.open()
        if settings.lbank_perp_api_key and settings.lbank_perp_secret_key:
            self.perp_client = LBankPerpClient(
                api_key=settings.lbank_perp_api_key,
                secret_key=settings.lbank_perp_secret_key,
                time_sync=self.perp_time,
            )
            await self.perp_client.open()

        async def _time_refresher() -> None:
            while True:
                try:
                    await self.spot_time.refresh()
                    await self.perp_time.refresh()
                except Exception as exc:
                    logger.error("time.refresh.error", error=str(exc))
                await asyncio.sleep(30)

        self._bg_tasks.append(asyncio.create_task(_time_refresher()))

    async def stop(self) -> None:
        for t in self._bg_tasks:
            t.cancel()
        if self.spot_client:
            await self.spot_client.close()
        if self.perp_client:
            await self.perp_client.close()


def admin_kb(state: AppState) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text=f"Mode: {state.mode}", callback_data="mode:menu")
    kb.button(text="Spot Balance", callback_data="spot:balance")
    kb.button(text="Perp Balance", callback_data="perp:balance")
    kb.button(text="Strategies", callback_data="strat:menu")
    kb.button(text="Time Drift", callback_data="time:drift")
    kb.adjust(1)
    return kb


def mode_kb(current: str) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for m in ("signal", "live"):
        prefix = "✅ " if m == current else ""
        kb.button(text=f"{prefix}{m}", callback_data=f"mode:set:{m}")
    kb.button(text="⬅️ Back", callback_data="admin:home")
    kb.adjust(2, 1)
    return kb


async def run_bot(stop_event: asyncio.Event) -> None:
    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher()

    state = AppState()
    await state.start()

    async def notify(event: str, payload: dict) -> None:
        # send to all admins; format Persian messages with compact, tabular batches
        def fmt_qty(q):
            try:
                return f"{float(q):.8f}".rstrip('0').rstrip('.')
            except Exception:
                return str(q)

        def pct(a, b):
            try:
                return (float(a) - float(b)) / float(b) * 100.0
            except Exception:
                return None

        msgs: list[tuple[str, str | None]] = []  # (text, parse_mode)
        if event in ("order_intent_batch", "order_live_batch"):
            intents = payload.get("intents", [])
            buys = [it for it in intents if it.get("side") == "buy"]
            sells = [it for it in intents if it.get("side") == "sell"]
            symbol = intents[0].get("symbol") if intents else "-"
            mode = payload.get("mode")
            title = ("⚡️ اجرای زنده" if event == "order_live_batch" else "🔔 سیگنال")

            # pick evenly spaced levels
            def pick_levels(items, k=3):
                try:
                    items = sorted(items, key=lambda x: float(x.get("price") or 0.0))
                except Exception:
                    items = items[:]
                n = len(items)
                if n <= k:
                    return items
                idxs = [round(i * (n - 1) / (k - 1)) for i in range(k)]
                seen = set()
                picked = []
                for i in idxs:
                    if i not in seen:
                        picked.append(items[i])
                        seen.add(i)
                return picked

            buys = pick_levels(buys, 6)
            sells = pick_levels(sells, 6)

            # center reference if available
            desc = payload.get("desc") or {}
            cur = desc.get("current") or {}
            center = cur.get("center")
            band = cur.get("band")

            # build plain text message, grouped and tidy
            header = f"{title} · {payload.get('strategy')} · {symbol} · حالت: {mode}"
            if center and band:
                header += f"\n🎯 مرکز: {center} · باند: {band[0]} — {band[1]}"

            lines: list[str] = [header]
            if buys:
                lines.append("🟢 خریدها:")
                for idx, it in enumerate(buys, 1):
                    p = it.get('price')
                    q = fmt_qty(it.get('quantity'))
                    sl = it.get('stop_loss') or "-"
                    tp = it.get('take_profit') or "-"
                    d = pct(p, center) if center else None
                    d_s = (f"{d:+.2f}%" if d is not None else "-")
                    lines.append(f"{idx}. 📦 {q} | 💲 {p} | Δ {d_s} | ⛔️ SL {sl} | 🎯 TP {tp}")
            if sells:
                lines.append("🔴 فروش‌ها:")
                for idx, it in enumerate(sells, 1):
                    p = it.get('price')
                    q = fmt_qty(it.get('quantity'))
                    sl = it.get('stop_loss') or "-"
                    tp = it.get('take_profit') or "-"
                    d = pct(p, center) if center else None
                    d_s = (f"{d:+.2f}%" if d is not None else "-")
                    lines.append(f"{idx}. 📦 {q} | 💲 {p} | Δ {d_s} | ⛔️ SL {sl} | 🎯 TP {tp}")

            text = "\n".join(lines)
            msgs.append((text, None))
        else:
            # single events for live placement
            if event == "order_placed":
                text = (
                    f"✅ سفارش ثبت شد · {payload.get('strategy')} · {payload.get('symbol')}\n"
                    f"{payload.get('type')} {payload.get('side')} | مقدار {payload.get('quantity')} @ {payload.get('price')}"
                )
                msgs.append((text, None))
            elif event == "order_error":
                text = (
                    f"⛔️ خطا در ثبت سفارش · {payload.get('strategy')} · {payload.get('symbol')}\n"
                    f"{payload.get('type')} {payload.get('side')} | مقدار {payload.get('quantity')} @ {payload.get('price')}\n"
                    f"Error: {payload.get('error')}"
                )
                msgs.append((text, None))
            else:
                text = f"[{event}] {payload.get('strategy')} {payload.get('symbol')} {payload.get('side')} {payload.get('quantity')} @ {payload.get('price')}"
                msgs.append((text, None))

        for text, parse_mode in msgs:
            for uid in admin_ids:
                try:
                    if parse_mode:
                        await bot.send_message(uid, text, parse_mode=parse_mode)
                    else:
                        await bot.send_message(uid, text)
                except Exception:
                    pass

    engine = StrategyEngine(spot_client=state.spot_client, perp_client=state.perp_client, notifier=notify)
    engine.load_plugins()
    await engine.start()

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

    @dp.callback_query(F.data == "strat:menu")
    async def cb_strat_menu(cb: CallbackQuery) -> None:
        items = engine.list()
        # Build inline toggles
        kb = InlineKeyboardBuilder()
        for it in items:
            status = "ON" if it['enabled'] else "OFF"
            kb.button(text=f"{it['name']} [{status}]", callback_data=f"strat:toggle:{it['name']}")
            kb.button(text=f"🔎 {it['name']}", callback_data=f"strat:desc:{it['name']}")
        kb.button(text="⬅️ Back", callback_data="admin:home")
        kb.adjust(2, 1)
        await cb.message.edit_text("Strategies:", reply_markup=kb.as_markup())
        await cb.answer()

    @dp.callback_query(F.data.startswith("strat:toggle:"))
    async def cb_strat_toggle(cb: CallbackQuery) -> None:
        name = cb.data.split(":", 2)[2]
        cur = next((x for x in engine.list() if x["name"] == name), None)
        if not cur:
            await cb.answer("Not found", show_alert=True)
            return
        engine.set_enabled(name, not cur["enabled"])
        await cb.answer("Toggled")
        await cb_strat_menu(cb)

    @dp.callback_query(F.data.startswith("strat:desc:"))
    async def cb_strat_desc(cb: CallbackQuery) -> None:
        name = cb.data.split(":", 2)[2]
        all_desc = await engine.describe_all()
        item = next((x for x in all_desc if x["name"] == name), None)
        if not item:
            await cb.answer("Not found", show_alert=True)
            return
        import json
        txt = json.dumps(item, ensure_ascii=False, indent=2)
        if len(txt) > 3500:
            txt = txt[:3500] + "..."
        await cb.message.edit_text(txt, reply_markup=admin_kb(state).as_markup())
        await cb.answer()

    @dp.callback_query(F.data == "mode:menu")
    async def cb_mode_menu(cb: CallbackQuery) -> None:
        await cb.message.edit_text("Select mode", reply_markup=mode_kb(state.mode).as_markup())
        await cb.answer()

    @dp.callback_query(F.data.startswith("mode:set:"))
    async def cb_mode_set(cb: CallbackQuery) -> None:
        mode = cb.data.split(":", 2)[2]
        state.mode = mode
        engine.mode = mode
        await cb.message.edit_text("Mode updated.", reply_markup=admin_kb(state).as_markup())
        await cb.answer("Mode set to %s" % mode)

    @dp.callback_query(F.data == "time:drift")
    async def cb_time_drift(cb: CallbackQuery) -> None:
        drift = abs(state.spot_time._offset_ms)
        await cb.answer()
        await cb.message.edit_text(f"Time drift: spot={abs(state.spot_time._offset_ms)} ms | perp={abs(state.perp_time._offset_ms)} ms", reply_markup=admin_kb(state).as_markup())

    @dp.callback_query(F.data == "spot:balance")
    async def cb_spot_balance(cb: CallbackQuery) -> None:
        if not state.spot_client:
            await cb.answer()
            await cb.message.edit_text("Spot API keys are missing.", reply_markup=admin_kb(state).as_markup())
            return
        try:
            data = await state.spot_client.user_info_account()
            balances = []
            # Accept variations: {data:{balances:[...]}} or {balances:[...]} or {balance:[...]}
            if isinstance(data, dict):
                d = data.get("data") or data
                balances = d.get("balances") or d.get("balance") or []
            lines = ["Asset  Free  Locked"]
            shown = 0
            for b in balances:
                asset = b.get("asset") or b.get("currency") or b.get("coin")
                free = b.get("free") or b.get("available")
                locked = b.get("locked") or b.get("freeze") or b.get("frozen")
                try:
                    f = float(str(free)) if free is not None else 0.0
                    l = float(str(locked)) if locked is not None else 0.0
                except Exception:
                    f = 0.0
                    l = 0.0
                if (f > 0) or (l > 0):
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

    @dp.callback_query(F.data == "perp:balance")
    async def cb_perp_balance(cb: CallbackQuery) -> None:
        if not state.perp_client:
            await cb.answer()
            await cb.message.edit_text("Perp API keys are missing.", reply_markup=admin_kb(state).as_markup())
            return
        try:
            data = await state.perp_client.account_balance()
            # Perp responses vary; normalize common shapes
            balances = []
            if isinstance(data, dict):
                d = data.get("data") or data
                # try common fields: balances, assets, account, list
                for key in ("balances", "assets", "account", "list", "positions"):
                    if isinstance(d.get(key), list):
                        balances = d.get(key)
                        break
            lines = ["Asset  Balance  Avail/Free  Frozen"]
            shown = 0
            for b in balances:
                asset = b.get("asset") or b.get("currency") or b.get("coin") or b.get("symbol")
                total = b.get("balance") or b.get("equity") or b.get("walletBalance")
                avail = b.get("available") or b.get("availableBalance") or b.get("free")
                frozen = b.get("frozen") or b.get("freeze") or b.get("marginFrozen")
                def to_f(x):
                    try:
                        return float(str(x)) if x is not None else 0.0
                    except Exception:
                        return 0.0
                if any(to_f(v) > 0 for v in (total, avail, frozen)):
                    lines.append(f"{asset}  {total}  {avail}  {frozen}")
                    shown += 1
                    if shown >= 30:
                        break
            text = "\n".join(lines) if shown else "No non-zero perp balances."
            await cb.message.edit_text(text, reply_markup=admin_kb(state).as_markup())
        except Exception as exc:
            await cb.message.edit_text(f"Perp balance error: {exc}", reply_markup=admin_kb(state).as_markup())
        finally:
            await cb.answer()

    async def _runner() -> None:
        try:
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types(), stop_event=stop_event)
        finally:
            await engine.stop()
            await state.stop()

    await _runner()

