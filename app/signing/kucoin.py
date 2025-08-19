from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass


def _b64_hmac_sha256(secret: str, msg: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


@dataclass
class KucoinSigner:
    api_key: str
    secret_key: str
    passphrase: str
    key_version: str = "2"

    def build_headers(self, timestamp_ms: str, method: str, request_path: str, body: str | None = None) -> dict[str, str]:
        str_to_sign = f"{timestamp_ms}{method.upper()}{request_path}{body or ''}"
        sign = _b64_hmac_sha256(self.secret_key, str_to_sign)
        # For v2, passphrase header is HMAC-SHA256 Base64 of original passphrase
        passphrase_header = _b64_hmac_sha256(self.secret_key, self.passphrase)
        return {
            "KC-API-KEY": self.api_key,
            "KC-API-SIGN": sign,
            "KC-API-TIMESTAMP": timestamp_ms,
            "KC-API-PASSPHRASE": passphrase_header,
            "KC-API-KEY-VERSION": self.key_version,
            "Content-Type": "application/json",
        }

