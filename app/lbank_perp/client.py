from __future__ import annotations

from typing import Any, Dict

from app.http import HttpClient
from app.signing import PerpSigner, random_echostr
from app.time_sync import TimeSynchronizer


PERP_BASE_URL = "https://lbkperp.lbank.com/"


class LBankPerpClient:
    def __init__(self, api_key: str, secret_key: str, time_sync: TimeSynchronizer, base_url: str | None = None) -> None:
        self.api_key = api_key
        self.signer = PerpSigner(secret_key=secret_key)
        self.time_sync = time_sync
        self.base_url = (base_url or PERP_BASE_URL).rstrip("/") + "/"
        self.http = HttpClient(self.base_url, headers={"X-Api-Key": self.api_key})

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
    async def server_time(self) -> Dict[str, Any]:
        resp = await self.http.get("cfd/openApi/v1/pub/getTime")
        return resp.json()

    async def instruments(self) -> Dict[str, Any]:
        resp = await self.http.get("cfd/openApi/v1/pub/instrument")
        return resp.json()

    async def market_data(self) -> Dict[str, Any]:
        resp = await self.http.get("cfd/openApi/v1/pub/marketData")
        return resp.json()

    # Private examples (actual endpoints should follow LBank Contract API specs)
    async def account_balance(self) -> Dict[str, Any]:
        base = await self._security_params()
        headers, signed = self.signer.build_headers_and_signature(base)
        resp = await self.http.post("cfd/openApi/v1/pri/account/balance", json=signed, headers=headers)
        return resp.json()
