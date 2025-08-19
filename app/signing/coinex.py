from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass


def _hmac_sha256_hex_lower(secret: str, msg: str) -> str:
    return hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest().lower()


@dataclass
class CoinexSigner:
    access_id: str
    secret_key: str
    window_time_ms: int = 5000

    def build_headers(self, method: str, request_path_with_query: str, body: str | None, timestamp_ms: str) -> dict[str, str]:
        raw = f"{method.upper()}{request_path_with_query}{body or ''}{timestamp_ms}"
        sign = _hmac_sha256_hex_lower(self.secret_key, raw)
        headers = {
            "X-COINEX-KEY": self.access_id,
            "X-COINEX-SIGN": sign,
            "X-COINEX-TIMESTAMP": timestamp_ms,
        }
        if self.window_time_ms and self.window_time_ms != 5000:
            headers["X-COINEX-WINDOWTIME"] = str(self.window_time_ms)
        return headers

