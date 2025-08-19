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
    async def _post_json(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        headers, signed = self.signer.build_headers_and_signature(payload)
        # Contract API expects headers for timestamp/signature_method/echostr
        resp = await self.http.post(path, json=signed, headers=headers)
        return resp.json()

    async def account_balance(self, asset: str = "USDT", product_group: str = "SwapU") -> Dict[str, Any]:
        base = await self._security_params()
        base.update({"api_key": self.api_key, "productGroup": product_group, "asset": asset})
        # Try a list of documented/variant endpoints; return first non-error response
        candidates = [
            "cfd/openApi/v1/prv/account",  # matches sample
            "cfd/openApi/v1/pri/account/balance",
            "cfd/openApi/v1/pri/account/getBalance",
            "cfd/openApi/v1/pri/account/info",
            "cfd/openApi/v1/pri/account/getAccountInfo",
            "cfd/openApi/v1/pri/account/getUserBalance",
        ]
        last = None
        for path in candidates:
            try:
                data = await self._post_json(path, base)
                # If success flag exists and is true, or no error_code
                if not isinstance(data, dict):
                    return data
                if data.get("success") in (True, "true", "True") or "error_code" not in data:
                    return data
                last = data
            except Exception as exc:
                last = {"error": str(exc), "path": path}
        return last or {"error": "no_response"}
