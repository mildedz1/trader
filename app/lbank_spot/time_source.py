from __future__ import annotations

from typing import Any

from app.http import HttpClient


SPOT_TIME_BASE = "https://api.lbkex.com/"


async def fetch_spot_server_time_ms() -> int:
    async with HttpClient(SPOT_TIME_BASE) as http:
        resp = await http.get("v2/timestamp.do")
        data: Any = resp.json()
        # LBank returns something like {"data": 1700000000000}
        if isinstance(data, dict) and "data" in data:
            return int(data["data"])  # type: ignore[arg-type]
        # Fallback if raw int
        try:
            return int(data)
        except Exception:
            raise ValueError("Unexpected timestamp response from LBank Spot")
