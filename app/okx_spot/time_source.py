from __future__ import annotations

from typing import Any

from app.http import HttpClient


BASE_URL = "https://www.okx.com/"


async def fetch_spot_server_time_ms() -> int:
    async with HttpClient(BASE_URL) as http:
        resp = await http.get("api/v5/public/time")
        data: Any = resp.json()
        # { "code": "0", "data": [{"ts": "1700000000000"}], "msg": "" }
        if isinstance(data, dict) and isinstance(data.get("data"), list) and data["data"]:
            ts = data["data"][0].get("ts")
            return int(ts)
        raise ValueError("Unexpected timestamp response from OKX")

