from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass


def _hmac_sha256_base64(key: str, msg: str) -> str:
    digest = hmac.new(key.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


@dataclass
class OkxSigner:
    api_key: str
    secret_key: str
    passphrase: str

    def build_headers(self, timestamp: str, method: str, request_path: str, body: str | None = None, simulated: bool = False) -> dict[str, str]:
        prehash = f"{timestamp}{method.upper()}{request_path}{body or ''}"
        sign = _hmac_sha256_base64(self.secret_key, prehash)
        headers: dict[str, str] = {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": sign,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }
        if simulated:
            headers["x-simulated-trading"] = "1"
        return headers

