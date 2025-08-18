from __future__ import annotations

import asyncio
import signal
from typing import List

from loguru import logger

from .core.config import Settings
from .core.logging import setup_logging
from .core.state import WorkerState
from .exchange_adapter.ccxt_lbank import CcxtLBankAdapter
from .exchange_adapter.lbank_futures import CcxtLBankFuturesAdapter
from .exchange_adapter.lbank_native import LBankNativeSpotClient
from .exchange_adapter.lbank_spot_native_adapter import LBankNativeSpotAdapter
from .exchange_adapter.lbank_futures_native import LBankNativeFuturesAdapter
from .strategy.logic import run_tick
from .strategy.futures_engine import run_tick_futures, FuturesState, FuturesPosition
import ccxt.async_support as ccxt  # keep import for runtime


class Worker:
	def __init__(self, settings: Settings):
		self.settings = settings
		self.state = WorkerState()
		self._shutdown = asyncio.Event()
		self.adapter = None
		self.native_spot: LBankNativeSpotClient | None = None
		self.fstate: FuturesState | None = None

	async def startup(self) -> None:
		logger.info("Use LBank API keys with Trade+Read only and Withdrawals disabled.")
		if not self.settings.lbank_api_key or not self.settings.lbank_api_secret:
			raise SystemExit("LBANK_API_KEY and LBANK_API_SECRET are required (live-only mode)")
		# Choose adapter
		if self.settings.trade_mode == "futures":
			if getattr(self.settings, "lbank_use_native_futures", False):
				self.adapter = LBankNativeFuturesAdapter(self.settings.lbank_api_key, self.settings.lbank_api_secret)
			else:
				self.adapter = CcxtLBankFuturesAdapter(self.settings.lbank_api_key, self.settings.lbank_api_secret)
		else:
			if self.settings.lbank_use_native_spot:
				self.adapter = LBankNativeSpotAdapter(self.settings.lbank_api_key, self.settings.lbank_api_secret)
			else:
				self.adapter = CcxtLBankAdapter(self.settings.lbank_api_key, self.settings.lbank_api_secret)
		await self.adapter.connect()
		# Prepare native spot client for robust spot orders
		if self.settings.trade_mode == "spot" and self.settings.lbank_use_native_spot:
			self.native_spot = LBankNativeSpotClient(self.settings.lbank_api_key, self.settings.lbank_api_secret)
			await self.native_spot.connect()
		# Initialize futures runtime state and try leverage/margin mode
		if self.settings.trade_mode == "futures":
			self.fstate = FuturesState(position=FuturesPosition())
			# Best-effort leverage/margin settings
			try:
				if hasattr(self.adapter, "set_leverage"):
					await self.adapter.set_leverage(self.settings.futures_symbol, int(self.settings.futures_leverage))  # type: ignore[attr-defined]
			except Exception:
				pass
			try:
				if hasattr(self.adapter, "set_position_mode"):
					await self.adapter.set_position_mode(self.settings.futures_symbol, str(self.settings.futures_position_mode))  # type: ignore[attr-defined]
			except Exception:
				pass
		logger.info("Connected to exchange adapter")

		async def balance_provider() -> str:
			# Helpers
			def _amount_from_balance(b: dict, code: str, which: str = "free") -> float:
				try:
					# prefer top-level mapping (ccxt normalized)
					m = b.get(which) or {}
					if isinstance(m, dict) and code in m:
						return float(m.get(code, 0.0))
					# per-currency dict (ccxt)
					c = b.get(code) or {}
					val = c.get(which) or c.get("total") or c.get("free")
					if val is not None:
						return float(val)
					# native spot supplement
					if "can_use" in b and isinstance(b["can_use"], dict):
						v = b["can_use"].get(code)
						if v is not None:
							return float(v)
					if "asset" in b and isinstance(b["asset"], dict):
						v = b["asset"].get(code)
						if v is not None:
							return float(v)
					return 0.0
				except Exception:
					return 0.0

			# Build Spot section
			spot_lines: list[str] = []
			try:
				spot_sym = self.settings.symbol
				base_ccy, quote_ccy = spot_sym.split("/")
				spot_bal: dict
				spot_price = 0.0
				if self.native_spot is not None:
					spot_bal = await self.native_spot.fetch_balance()
					spot_price = await self.native_spot.ticker_price(spot_sym)
				else:
					# use a temporary ccxt spot client
					import ccxt.async_support as _ccxt
					client = _ccxt.lbank({
						"apiKey": self.settings.lbank_api_key or "",
						"secret": self.settings.lbank_api_secret or "",
						"enableRateLimit": True,
						"options": {"defaultType": "spot"},
					})
					try:
						await client.load_markets()
						spot_bal = await client.fetch_balance()
						t = await client.fetch_ticker(spot_sym)
						spot_price = float(t.get("last") or t.get("close") or 0.0)
					finally:
						try:
							await client.close()
						except Exception:
							pass
				spot_base = _amount_from_balance(spot_bal, base_ccy, "free")
				spot_usdt = _amount_from_balance(spot_bal, quote_ccy, "free")
				spot_equity = spot_usdt + spot_base * spot_price
				spot_lines = [
					"حساب اسپات:",
					f"موجودی {quote_ccy}: {spot_usdt:.4f}",
					f"موجودی {base_ccy}: {spot_base:.8f}",
					f"قیمت {spot_sym}: {spot_price:.4f}",
					f"اکویتی تقریبی: {spot_equity:.4f} USDT",
				]
			except Exception:
				pass

			# Build Futures section
			fut_lines: list[str] = []
			try:
				fut_sym = self.settings.futures_symbol
				# prefer native futures client if enabled
				f_usdt = None
				if getattr(self.settings, "lbank_use_native_futures", False):
					from .exchange_adapter.lbank_futures_native import LBankNativeFuturesClient as _NF
					nfc = _NF(self.settings.lbank_api_key or "", self.settings.lbank_api_secret or "")
					await nfc.connect()
					try:
						acc = await nfc.account_balance(asset="USDT", product_group="SwapU")
						# Expect { data: {available: ...} } or similar; try common fields
						data = acc.get("data") if isinstance(acc, dict) else acc
						if isinstance(data, dict):
							f_usdt = float(data.get("available") or data.get("avail") or data.get("equity") or 0.0)
					finally:
						try:
							await nfc.close()
						except Exception:
							pass
				if f_usdt is None:
					# fallback ccxt futures client
					import ccxt.async_support as _ccxt
					client = _ccxt.lbank({
						"apiKey": self.settings.lbank_api_key or "",
						"secret": self.settings.lbank_api_secret or "",
						"enableRateLimit": True,
						"options": {"defaultType": "swap"},
					})
					try:
						await client.load_markets()
						fut_bal = await client.fetch_balance()
						def _amount_from_balance(b: dict, code: str, which: str = "free") -> float:
							try:
								m = b.get(which) or {}
								if code in m:
									return float(m.get(code, 0.0))
								c = b.get(code) or {}
								val = c.get(which) or c.get("total") or c.get("free") or 0.0
								return float(val)
							except Exception:
								return 0.0
						f_usdt = _amount_from_balance(fut_bal, "USDT", "free")
					finally:
						try:
							await client.close()
						except Exception:
							pass
				fut_lines = [
					"حساب فیوچرز (USDT-M):",
					f"مارجین USDT (در دسترس): {float(f_usdt or 0.0):.4f}",
				]
			except Exception:
				pass

			return "\n".join([*spot_lines, "", *fut_lines]).strip()

		self.state.balance_provider = balance_provider

		async def position_overview() -> str:
			sym = self.settings.futures_symbol if self.settings.trade_mode == "futures" else self.settings.symbol
			base_ccy, _ = sym.split("/")
			ticker = await self.adapter.fetch_ticker(sym)
			price = float(ticker.get("last") or ticker.get("close") or 0.0)
			lines: list[str] = []
			if self.settings.trade_mode == "futures" and self.fstate is not None:
				pos = self.fstate.position
				pnl = 0.0
				if pos.size_base > 0 and pos.entry_price > 0:
					if pos.is_long:
						pnl = (price - pos.entry_price) * pos.size_base
					else:
						pnl = (pos.entry_price - price) * pos.size_base
				lines = [
					"پوزیشن فیوچرز:",
					f"- لانگ: {pos.is_long}",
					f"- شورت: {pos.is_short}",
					f"- اندازه: {pos.size_base:.6f} {base_ccy}",
					f"- قیمت ورود: {pos.entry_price:.4f}",
					f"- SL/TP: {pos.sl:.4f} / {pos.tp:.4f}",
					f"- قیمت فعلی: {price:.4f}",
					f"- PnL تقریبی: {pnl:.4f} USDT",
				]
			else:
				pnl = 0.0
				if self.state.position.is_long and self.state.position.quantity > 0 and self.state.position.entry_price > 0:
					pnl = (price - self.state.position.entry_price) * self.state.position.quantity
				lines = [
					"سفارش/پوزیشن اسپات:",
					f"- لانگ: {self.state.position.is_long}",
					f"- مقدار: {self.state.position.quantity:.6f} {base_ccy}",
					f"- قیمت ورود: {self.state.position.entry_price:.4f}",
					f"- قیمت فعلی: {price:.4f}",
					f"- PnL تقریبی: {pnl:.4f} USDT",
				]
			# Also list open orders on the symbol (if any)
			try:
				orders = await self.adapter.fetch_open_orders(sym)
				if orders:
					lines.append("")
					lines.append("سفارش‌های باز:")
					for o in orders[:10]:
						side = o.get("side", "?")
						type_ = o.get("type", "?")
						amt = o.get("amount") or o.get("remaining") or 0
						price_o = o.get("price") or 0
						lines.append(f"- {side.upper()} {type_} amount={amt} price={price_o}")
			except Exception:
				pass
			return "\n".join(lines)

		async def check_signal() -> str:
			# Fetch latest required data and evaluate once
			required_n = max(200, int(self.settings.ema_slow) + 1, int(self.settings.macd_slow) + int(self.settings.macd_signal) + 1)
			ohlcv = await self.fetch_ohlcv(limit=max(required_n + 5, 220))
			if not ohlcv or len(ohlcv) < required_n:
				return "داده کافی برای ارزیابی سیگنال وجود ندارد."
			closes = [float(c[4]) for c in ohlcv]
			from .strategy.logic import evaluate_macd_zero_trend, compute_position_size_usdt_capped
			res = evaluate_macd_zero_trend(closes, self.settings)
			trend_ok = res.extra.get('trend_ok', 0.0) == 1.0
			zero_up = res.extra.get('zero_up', 0.0) == 1.0
			# Sizing & min rules
			ticker_price = closes[-1]
			amount_base_cap, amount_quote_cap = await compute_position_size_usdt_capped(self.adapter, self.settings, ticker_price)
			min_cost = 0.0
			min_amount = 0.0
			try:
				mr = self.adapter.get_market_rules(self.settings.symbol)  # type: ignore[attr-defined]
				min_cost = float(mr.get('min_cost', 0.0))
				min_amount = float(mr.get('min_amount', 0.0))
			except Exception:
				pass
			notional = amount_base_cap * ticker_price
			entry_possible = res.should_long and (notional >= max(min_cost, 0.0)) and (amount_base_cap >= max(min_amount, 0.0))
			reasons = []
			if not res.should_long:
				reasons.append('تریگر ورود فعال نیست')
			if notional < max(min_cost, 0.0):
				reasons.append(f'کمتر از حداقل ارزش سفارش صرافی: notional={notional:.4f} < min_cost={min_cost}')
			if amount_base_cap < max(min_amount, 0.0):
				reasons.append(f'کمتر از حداقل مقدار: amount={amount_base_cap:.8f} < min_amount={min_amount}')
			msg = (
				f"Trend OK: {'بله' if trend_ok else 'خیر'}\n"
				f"MACD zero-up: {'بله' if zero_up else 'خیر'}\n"
				f"should_long={res.should_long} should_exit={res.should_exit}\n"
				f"price={ticker_price:.4f} amount_base_cap={amount_base_cap:.8f} notional={notional:.4f} USDT\n"
				f"min_cost={min_cost} min_amount={min_amount}\n"
				f"entry_possible={'بله' if entry_possible else 'خیر'}"
			)
			if reasons:
				msg += "\nدلایل: " + "; ".join(reasons)
			return msg

		async def manual_buy() -> str:
			try:
				sym = self.settings.futures_symbol if self.settings.trade_mode == "futures" else self.settings.symbol
				if self.settings.trade_mode == "spot" and self.native_spot is not None:
					# Use native REST spot order
					order = await self.native_spot.create_market_buy_quote(sym, 1.0)  # hard cap 1 USDT
					return f"خرید دستی (Spot/Native) انجام شد: {order}"
				else:
					# Futures or fallback to ccxt spot
					if self.settings.trade_mode == "futures":
						bal = await self.adapter.fetch_balance()
						def _amount_from_balance(b: dict, code: str, which: str = "free") -> float:
							try:
								m = b.get(which) or {}
								if code in m:
									return float(m.get(code, 0.0))
								c = b.get(code) or {}
								val = c.get(which) or c.get("total") or c.get("free") or 0.0
								return float(val)
							except Exception:
								return 0.0
						usdt_free = _amount_from_balance(bal, "USDT", "free")
						ticker = await self.adapter.fetch_ticker(sym)
						price = float(ticker.get("last") or ticker.get("close") or 0.0)
						lev = float(getattr(self.settings, "futures_leverage", 1))
						if price <= 0 or usdt_free <= 0:
							return "امکان خرید نیست: قیمت/موجودی نامعتبر"
						margin_usdt = usdt_free if getattr(self.settings, "use_full_balance", True) else min(usdt_free, 1.0)
						base_size = (margin_usdt * lev) / max(price, 1e-8)
						# Enforce precision and min amount
						min_amount = 0.0
						try:
							mr = self.adapter.get_market_rules(sym)  # type: ignore[attr-defined]
							min_amount = float(mr.get("min_amount", 0.0))
						except Exception:
							pass
						if hasattr(self.adapter, "round_amount"):
							base_size = self.adapter.round_amount(sym, base_size)  # type: ignore[attr-defined]
						if base_size < max(min_amount, 0.0):
							needed_margin = (max(min_amount, 0.0) * price) / max(lev, 1.0)
							return (
								f"سایز ناکافی نسبت به حداقل ({base_size:.6f} < {min_amount}); "
								f"حداقل مارجین لازم ≈ {needed_margin:.4f} USDT با لوریج {lev}."
							)
						# Place futures market BUY using base size and explicit price for LBank
						if hasattr(self.adapter, "create_market_order"):
							order = await self.adapter.create_market_order(sym, "buy", base_size)  # type: ignore[attr-defined]
						else:
							# Fallback: convert to base with price and call create_market_buy_order which passes price for LBank
							order = await self.adapter.create_market_buy_order(sym, margin_usdt)
						return f"خرید دستی (Futures) انجام شد: {order}"
					else:
						# ccxt spot fallback when native spot disabled
						ticker = await self.adapter.fetch_ticker(sym)
						price = float(ticker.get("last") or ticker.get("close") or 0.0)
						from .strategy.logic import compute_position_size_usdt_capped
						amount_base_cap, amount_quote_cap = await compute_position_size_usdt_capped(self.adapter, self.settings, price)
						if amount_quote_cap <= 0 or amount_base_cap <= 0:
							return "امکان خرید نیست: موجودی/سایز ناکافی"
						order = await self.adapter.create_market_buy_order(sym, amount_quote_cap)
						return f"خرید دستی انجام شد: {order}"
			except Exception as exc:
				return f"خرید دستی ناموفق بود: {exc}"

		async def manual_close() -> str:
			try:
				sym = self.settings.futures_symbol if self.settings.trade_mode == "futures" else self.settings.symbol
				if self.settings.trade_mode == "spot" and self.native_spot is not None:
					# Native spot sell by base amount up to ~1 USDT
					bal = await self.adapter.fetch_balance()
					base_ccy = sym.split("/")[0]
					base = float((bal.get("free") or bal.get("total") or {}).get(base_ccy, 0.0))
					if base <= 0:
						return "هیچ پوزیشن/موجودی برای فروش وجود ندارد"
					# sell up to 1 USDT notional
					price = await self.native_spot.ticker_price(sym)
					notional = min(base * price, 1.0)
					amount_to_sell = notional / price if price > 0 else 0.0
					order = await self.native_spot.create_market_sell_base(sym, amount_to_sell)
					return f"فروش دستی (Spot/Native) انجام شد: {order}"
				else:
					if self.settings.trade_mode == "futures" and self.fstate is not None and not self.fstate.position.flat():
						pos = self.fstate.position
						amt = pos.size_base
						if amt <= 0:
							return "پوزیشنی برای بستن وجود ندارد"
						# Close with opposite side reduce-only if available
						if hasattr(self.adapter, "create_market_order"):
							side = "sell" if pos.is_long else "buy"
							order = await self.adapter.create_market_order(sym, side, amt, reduce_only=True)  # type: ignore[attr-defined]
							pos.reset()
							return f"بستن دستی فیوچرز انجام شد: {order}"
						# Fallback: emulate
						if pos.is_long:
							order = await self.adapter.create_market_sell_order(sym, amt)
						else:
							# buy requires quote; approximate using ticker
							ticker = await self.adapter.fetch_ticker(sym)
							price = float(ticker.get("last") or ticker.get("close") or 0.0)
							order = await self.adapter.create_market_buy_order(sym, amt * price)
						pos.reset()
						return f"بستن دستی فیوچرز انجام شد: {order}"
					# Spot ccxt fallback
					bal = await self.adapter.fetch_balance()
					base_ccy = sym.split("/")[0]
					base = float((bal.get("free") or bal.get("total") or {}).get(base_ccy, 0.0))
					if base <= 0:
						return "هیچ پوزیشن/موجودی برای فروش وجود ندارد"
					ticker = await self.adapter.fetch_ticker(sym)
					price = float(ticker.get("last") or ticker.get("close") or 0.0)
					notional = min(base * price, 1.0)
					amount_to_sell = notional / price if price > 0 else 0.0
					order = await self.adapter.create_market_sell_order(sym, amount_to_sell)
					return f"فروش دستی انجام شد: {order}"
			except Exception as exc:
				return f"فروش دستی ناموفق بود: {exc}"

		self.state.check_signal = check_signal
		self.state.manual_buy = manual_buy
		self.state.manual_close = manual_close
		self.state.position_overview = position_overview

		async def manual_force_long() -> str:
			# Enter long immediately (ignores strategy), based on current mode
			try:
				if self.settings.trade_mode == "futures":
					sym = self.settings.futures_symbol
					bal = await self.adapter.fetch_balance()
					usdt = float((bal.get("free") or {}).get("USDT", 0.0))
					if usdt <= 0:
						return "موجودی کافی برای ورود لانگ وجود ندارد"
					ticker = await self.adapter.fetch_ticker(sym)
					price = float(ticker.get("last") or ticker.get("close") or 0.0)
					lev = float(getattr(self.settings, "futures_leverage", 1))
					margin_usdt = usdt if getattr(self.settings, "use_full_balance", True) else min(usdt, 1.0)
					base_size = (margin_usdt * lev) / max(price, 1e-8)
					if hasattr(self.adapter, "round_amount"):
						base_size = self.adapter.round_amount(sym, base_size)  # type: ignore[attr-defined]
					order = await self.adapter.create_market_order(sym, "buy", base_size)  # type: ignore[attr-defined]
					return f"ورود فوری لانگ (Futures) انجام شد: {order}"
				else:
					sym = self.settings.symbol
					order = await self.adapter.create_market_buy_order(sym, 1.0)
					return f"ورود فوری لانگ (Spot) انجام شد: {order}"
			except Exception as exc:
				return f"ورود فوری لانگ ناموفق بود: {exc}"

		async def manual_force_short() -> str:
			# Enter short immediately (futures only)
			try:
				if self.settings.trade_mode != "futures":
					return "شورت فقط در فیوچرز پشتیبانی می‌شود"
				sym = self.settings.futures_symbol
				ticker = await self.adapter.fetch_ticker(sym)
				price = float(ticker.get("last") or ticker.get("close") or 0.0)
				bal = await self.adapter.fetch_balance()
				usdt = float((bal.get("free") or {}).get("USDT", 0.0))
				lev = float(getattr(self.settings, "futures_leverage", 1))
				margin_usdt = usdt if getattr(self.settings, "use_full_balance", True) else min(usdt, 1.0)
				base_size = (margin_usdt * lev) / max(price, 1e-8)
				if hasattr(self.adapter, "round_amount"):
					base_size = self.adapter.round_amount(sym, base_size)  # type: ignore[attr-defined]
				order = await self.adapter.create_market_order(sym, "sell", base_size)  # type: ignore[attr-defined]
				return f"ورود فوری شورت (Futures) انجام شد: {order}"
			except Exception as exc:
				return f"ورود فوری شورت ناموفق بود: {exc}"

		self.state.manual_force_long = manual_force_long
		self.state.manual_force_short = manual_force_short

	async def fetch_ohlcv(self, limit: int = 300):
		# Use the already-connected adapter to avoid extra load_markets calls and CF rate limits
		sym = self.settings.futures_symbol if self.settings.trade_mode == "futures" else self.settings.symbol
		tf = self.settings.futures_timeframe if self.settings.trade_mode == "futures" else self.settings.timeframe
		return await self.adapter.fetch_ohlcv(sym, timeframe=tf, limit=limit)

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
				if self.settings.trade_mode == "futures" and self.fstate is not None:
					await run_tick_futures(self.adapter, self.state, self.fstate, self.settings, ohlcv, candle_ts=last_closed_ts)
				else:
					await run_tick(self.adapter, self.state, self.settings, closes, candle_ts=last_closed_ts)
			except Exception as exc:  # noqa: BLE001
				logger.exception(f"Worker tick error: {exc}")
			await asyncio.sleep(interval)

	async def shutdown(self) -> None:
		self._shutdown.set()
		try:
			if self.adapter:
				await self.adapter.close()
			if self.native_spot:
				await self.native_spot.close()
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