from __future__ import annotations

from typing import Any

from app.http import HttpClient


PERP_TIME_BASE = "https://lbkperp.lbank.com/"


async def fetch_perp_server_time_ms() -> int:
    async with HttpClient(PERP_TIME_BASE) as http:
        resp = await http.get("cfd/openApi/v1/pub/getTime")
        data: Any = resp.json()
        if isinstance(data, dict) and "data" in data:
            # Some responses nest time in data or directly return int
            val = data["data"]
            try:
                return int(val)
            except Exception:
                # If nested like {data: {serverTime: ...}}
                if isinstance(val, dict):
                    for key in ("serverTime", "timestamp", "time"):
                        if key in val:
                            return int(val[key])
            raise ValueError("Unexpected timestamp payload in Perp response")
        try:
            return int(data)
        except Exception:
            raise ValueError("Unexpected timestamp response from LBank Perp")
