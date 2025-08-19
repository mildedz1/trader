from __future__ import annotations

from typing import Any

from app.http import HttpClient


BASE_URL = "https://api.coinex.com/"


async def fetch_spot_server_time_ms() -> int:
    async with HttpClient(BASE_URL) as http:
        resp = await http.get("v2/common/svr-time")
        data: Any = resp.json()
        # coinex v2 often returns {code: 0, data: {timestamp: 1700000000000}}
        if isinstance(data, dict):
            d = data.get("data")
            if isinstance(d, dict) and "timestamp" in d:
                try:
                    return int(d["timestamp"])  # type: ignore[arg-type]
                except Exception:
                    pass
            for key in ("serverTime", "time", "ts"):
                if key in data:
                    return int(data[key])  # type: ignore[arg-type]
        # fallback raw int
        try:
            return int(data)
        except Exception:
            raise ValueError("Unexpected timestamp response from CoinEx")

