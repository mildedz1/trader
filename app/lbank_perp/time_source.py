from __future__ import annotations

from typing import Any

from app.http import HttpClient


PERP_TIME_BASE = "https://lbkperp.lbank.com/"


async def fetch_perp_server_time_ms() -> int:
    async with HttpClient(PERP_TIME_BASE) as http:
        resp = await http.get("cfd/openApi/v1/pub/getTime")
        data: Any = resp.json()
        if isinstance(data, dict) and "data" in data:
            return int(data["data"])  # type: ignore[arg-type]
        try:
            return int(data)
        except Exception:
            raise ValueError("Unexpected timestamp response from LBank Perp")
