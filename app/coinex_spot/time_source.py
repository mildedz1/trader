from __future__ import annotations

from typing import Any
import time

from app.http import HttpClient
from app.logging import logger


BASE_URL = "https://api.coinex.com/"


async def fetch_spot_server_time_ms() -> int:
    async with HttpClient(BASE_URL) as http:
        paths = [
            "v2/common/svr-time",
            "v2/common/server-time",
            "v2/common/time",
            "v1/common/servertime",
        ]
        last_err: str | None = None
        for p in paths:
            try:
                resp = await http.get(p)
                data: Any = resp.json()
                if isinstance(data, dict):
                    d = data.get("data") or data
                    # common shapes
                    for key in ("timestamp", "serverTime", "time", "ts"):
                        if key in d:
                            return int(d[key])  # type: ignore[arg-type]
                try:
                    return int(data)
                except Exception:
                    last_err = f"unexpected payload: {str(data)[:120]}"
            except Exception as exc:
                last_err = str(exc)
                continue
        # Final fallback to local time to avoid startup crash
        logger.warn("coinex.time.fallback_local", error=last_err)
        return int(time.time() * 1000)

