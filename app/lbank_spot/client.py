from __future__ import annotations

import asyncio
import secrets
from typing import Any, Dict, Optional

from app.http import HttpClient
from app.signing import SpotSigner, random_echostr
from app.time_sync import TimeSynchronizer
from app.logging import logger


SPOT_BASE_URLS = [
    "https://api.lbkex.com/",
    "https://api.lbank.info/",
    # Some regions route supplement endpoints differently
    "https://api.lbkex.net/",
    # Web domain sometimes carries private endpoints
    "https://www.lbkex.net/",
]


class LBankSpotClient:
    def __init__(self, api_key: str, secret_key: str, time_sync: TimeSynchronizer, base_url: str | None = None) -> None:
        self.api_key = api_key
        self.signer = SpotSigner(secret_key=secret_key)
        self.time_sync = time_sync
        self.base_url = (base_url or SPOT_BASE_URLS[0]).rstrip("/") + "/"
        # Do not send non-standard headers by default; LBank expects security headers only
        self.http = HttpClient(self.base_url)
        # Map lowercase -> canonical symbol as returned by API (case preserved)
        self._pair_map: dict[str, str] = {}

    async def open(self) -> None:
        await self.http.open()

    async def close(self) -> None:
        await self.http.close()

    async def _security_params(self) -> Dict[str, str]:
        ts = self.time_sync.now_ms()
        return {
            "api_key": self.api_key,
            "timestamp": str(ts),
            "signature_method": "HmacSHA256",
            "echostr": random_echostr(32),
        }

    # Public
    async def system_ping(self) -> Dict[str, Any]:
        resp = await self.http.get("v2/supplement/system_ping.do")
        return resp.json()

    async def server_time(self) -> Dict[str, Any]:
        resp = await self.http.get("v2/timestamp.do")
        return resp.json()

    async def ticker_price(self, symbol: str) -> Dict[str, Any]:
        # Use canonical symbol if available
        try:
            sym = await self.normalize_symbol(symbol)
        except Exception:
            sym = symbol
        # Try multiple official endpoints to maximize compatibility across regions/versions
        endpoints = [
            ("v2/supplement/ticker/price.do", {"symbol": sym}),
            ("v2/supplement/ticker/bookTicker.do", {"symbol": sym}),
            ("v2/supplement/ticker/24hr.do", {"symbol": sym}),
            ("v2/ticker/24hr.do", {"symbol": sym}),
            ("v2/ticker.do", {"symbol": sym}),
        ]
        last_exc: Optional[Exception] = None
        for path, params in endpoints:
            try:
                resp = await self.http.get(path, params=params)
                return resp.json()
            except Exception as exc:
                last_exc = exc
                continue
        if last_exc:
            raise last_exc
        return {}

    async def ticker_24hr(self, symbol: str | None = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if symbol:
            try:
                params["symbol"] = await self.normalize_symbol(symbol)
            except Exception:
                params["symbol"] = symbol
        resp = await self.http.get("v2/supplement/ticker/24hr.do", params=params)
        return resp.json()

    async def currency_pairs(self) -> dict[str, str]:
        if self._pair_map:
            return self._pair_map
        resp = await self.http.get("v2/currencyPairs.do")
        data = resp.json()
        mapping: dict[str, str] = {}
        if isinstance(data, dict) and "data" in data:
            for s in data["data"]:
                s_str = str(s)
                mapping[s_str.lower()] = s_str
        elif isinstance(data, list):
            for s in data:
                s_str = str(s)
                mapping[s_str.lower()] = s_str
        self._pair_map = mapping
        return self._pair_map

    async def normalize_symbol(self, symbol: str) -> str:
        pairs = await self.currency_pairs()
        sl = symbol.lower().replace("/", "_")
        if sl in pairs:
            return pairs[sl]
        raise ValueError(f"Unsupported symbol on LBank spot: {symbol}")

    # Private
    async def create_order_test(self, params: Dict[str, str]) -> Dict[str, Any]:
        base = await self._security_params()
        data = {**params, **base}
        headers, signed = self.signer.build_headers_and_signature(data)
        resp = await self.http.post("v2/supplement/create_order_test.do", data=signed, headers=headers)
        return resp.json()

    async def create_order(self, params: Dict[str, str]) -> Dict[str, Any]:
        base = await self._security_params()
        data = {**params, **base}
        # Resolve symbol to canonical case from exchange; if missing, let it pass as-is
        primary_symbol: Optional[str] = None
        if "symbol" in data and data["symbol"]:
            try:
                primary_symbol = await self.normalize_symbol(str(data["symbol"]))
                data["symbol"] = primary_symbol
            except Exception:
                pass
        # Normalize order type: use buy/sell only; market indicated by price=0
        t = str(data.get("type", "")).lower()
        if t in ("buy_market", "sell_market"):
            data["type"] = "buy" if "buy" in t else "sell"
            data["price"] = "0"
        async def _post_with(http: HttpClient, payload: Dict[str, str], path: str) -> Dict[str, Any]:
            headers, signed = self.signer.build_headers_and_signature(payload)
            resp = await http.post(path, data=signed, headers=headers)
            return resp.json()

        # Try primary base first
        try:
            out = await _post_with(self.http, data, "v2/supplement/create_order.do")
        except Exception as exc:
            # Network/DNS error: try alternates immediately
            out = {"error_code": -1, "msg": str(exc)}
        # Fallback attempts if currency pair nonsupport: try lowercase and uppercase variants
        try:
            code = (out or {}).get("error_code")
        except Exception:
            code = None
        if code == 10008 and data.get("symbol"):
            sym = str(data["symbol"])
            candidates = []
            if primary_symbol and primary_symbol != sym:
                candidates.append(primary_symbol)
            if sym.lower() != sym:
                candidates.append(sym.lower())
            if sym.upper() != sym:
                candidates.append(sym.upper())
            # Try alternate separators
            def alt_seps(s: str) -> list[str]:
                out_syms: list[str] = []
                s_low = s.lower()
                base, quote = (s_low.split("_", 1) if "_" in s_low else (s_low, ""))
                if quote:
                    out_syms += [
                        f"{base}_{quote}",
                        f"{base}-{quote}",
                        f"{base}/{quote}",
                        f"{base.upper()}_{quote.upper()}",
                        f"{base.upper()}-{quote.upper()}",
                        f"{base.upper()}/{quote.upper()}",
                    ]
                return out_syms
            for altf in alt_seps(sym):
                if altf not in candidates:
                    candidates.append(altf)
            for alt in candidates:
                data_alt = {**params, **base, "symbol": alt}
                # Preserve normalized type semantics
                tt = str(data_alt.get("type", "")).lower()
                if tt in ("buy_market", "sell_market"):
                    data_alt["type"] = "buy" if "buy" in tt else "sell"
                    data_alt["price"] = "0"
                out_alt = await _post_with(self.http, data_alt, "v2/supplement/create_order.do")
                try:
                    code_alt = (out_alt or {}).get("error_code")
                except Exception:
                    code_alt = None
                if not code_alt:
                    return out_alt
            # If still failing, try alternate param key (pair) and endpoints and base URLs
            def build_variants(symbol_value: str) -> list[Dict[str, str]]:
                v: list[Dict[str, str]] = []
                common = {k: v for k, v in data.items() if k not in ("symbol", "pair")}
                v.append({**common, "symbol": symbol_value})
                v.append({**common, "pair": symbol_value})
                return v

            endpoint_paths = [
                "v2/supplement/create_order.do",
                "v2/create_order.do",
            ]

            for base_url in SPOT_BASE_URLS:
                if self.base_url == base_url.rstrip("/") + "/":
                    continue
                http_alt = HttpClient(base_url)
                try:
                    await http_alt.open()
                    # try endpoints and param variants
                    for path in endpoint_paths:
                        # try original, then symbol variants
                        for payload in [data] + [
                            {**params, **base, "symbol": alt} for alt in candidates
                        ]:
                            # normalize market type semantics
                            tt = str(payload.get("type", "")).lower()
                            payload = payload.copy()
                            if tt in ("buy_market", "sell_market"):
                                payload["type"] = "buy" if "buy" in tt else "sell"
                                payload["price"] = "0"
                            # try with symbol and pair key permutations
                            for p in build_variants(str(payload.get("symbol") or payload.get("pair") or sym)):
                                try:
                                    out_variant = await _post_with(http_alt, p, path)
                                except Exception:
                                    continue
                                code_v = (out_variant or {}).get("error_code")
                                if not code_v:
                                    return out_variant
                finally:
                    await http_alt.close()
        return out

    async def cancel_order(self, params: Dict[str, str]) -> Dict[str, Any]:
        base = await self._security_params()
        data = {**params, **base}
        headers, signed = self.signer.build_headers_and_signature(data)
        resp = await self.http.post("v2/supplement/cancel_order.do", data=signed, headers=headers)
        return resp.json()

    async def cancel_order_by_symbol(self, params: Dict[str, str]) -> Dict[str, Any]:
        base = await self._security_params()
        data = {**params, **base}
        headers, signed = self.signer.build_headers_and_signature(data)
        resp = await self.http.post("v2/supplement/cancel_order_by_symbol.do", data=signed, headers=headers)
        return resp.json()

    async def orders_info(self, params: Dict[str, str]) -> Dict[str, Any]:
        base = await self._security_params()
        data = {**params, **base}
        headers, signed = self.signer.build_headers_and_signature(data)
        resp = await self.http.post("v2/supplement/orders_info.do", data=signed, headers=headers)
        return resp.json()

    async def user_info_account(self) -> Dict[str, Any]:
        base = await self._security_params()
        headers, signed = self.signer.build_headers_and_signature(base)
        resp = await self.http.post("v2/supplement/user_info_account.do", data=signed, headers=headers)
        return resp.json()