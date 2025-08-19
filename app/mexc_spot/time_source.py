from __future__ import annotations

from typing import Any

from app.http import HttpClient


SPOT_TIME_BASE = "https://api.mexc.com/"


async def fetch_spot_server_time_ms() -> int:
    async with HttpClient(SPOT_TIME_BASE) as http:
        resp = await http.get("api/v3/time")
        data: Any = resp.json()
        # MEXC returns something like {"serverTime": 1700000000000}
        if isinstance(data, dict):
            for key in ("serverTime", "timestamp", "time"):
                if key in data:
                    return int(data[key])  # type: ignore[arg-type]
        # Fallback if raw int
        try:
            return int(data)
        except Exception:
            raise ValueError("Unexpected timestamp response from MEXC Spot")

