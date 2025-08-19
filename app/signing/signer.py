from __future__ import annotations

import hashlib
import hmac
import secrets
import string
from dataclasses import dataclass
from typing import Dict, Mapping, Tuple

from app.logging import logger


def random_echostr(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    length = max(30, min(40, length))
    return "".join(secrets.choice(alphabet) for _ in range(length))


def build_pre_md5_string(params: Mapping[str, str]) -> str:
    # Sort by parameter name ascending, join as key=value&key2=value2...
    items = sorted((k, v) for k, v in params.items() if v is not None)
    return "&".join(f"{k}={v}" for k, v in items)


def md5_upper_hex(data: str) -> str:
    return hashlib.md5(data.encode("utf-8")).hexdigest().upper()


def hmac_sha256_hex(key: str, msg: str) -> str:
    digest = hmac.new(key.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest


@dataclass
class SpotSigner:
    secret_key: str
    signature_method: str = "HmacSHA256"  # or "RSA"

    def build_headers_and_signature(self, params: Dict[str, str]) -> Tuple[Dict[str, str], Dict[str, str]]:
        if "timestamp" not in params or "signature_method" not in params or "echostr" not in params:
            raise ValueError("Missing security parameters: timestamp, signature_method, echostr")

        # Build sign from all fields (including security triplet), excluding sign itself
        pre_md5 = build_pre_md5_string({k: v for k, v in params.items() if k != "sign"})
        md5_u = md5_upper_hex(pre_md5)
        sign = hmac_sha256_hex(self.secret_key, md5_u)

        # Move security fields into headers per LBank requirement
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "timestamp": str(params["timestamp"]),
            "signature_method": params.get("signature_method", self.signature_method),
            "echostr": params["echostr"],
        }
        body = {k: v for k, v in params.items() if k not in {"timestamp", "signature_method", "echostr", "sign"}}
        body["sign"] = sign
        return headers, body


@dataclass
class PerpSigner:
    secret_key: str
    signature_method: str = "HmacSHA256"

    def build_headers_and_signature(self, params: Dict[str, str]) -> Tuple[Dict[str, str], Dict[str, str]]:
        if "timestamp" not in params or "signature_method" not in params or "echostr" not in params:
            raise ValueError("Missing security parameters: timestamp, signature_method, echostr")
        pre_md5 = build_pre_md5_string({k: v for k, v in params.items() if k != "sign"})
        md5_u = md5_upper_hex(pre_md5)
        sign = hmac_sha256_hex(self.secret_key, md5_u)
        headers = {
            "Content-Type": "application/json",
            "timestamp": str(params["timestamp"]),
            "signature_method": params.get("signature_method", self.signature_method),
            "echostr": params["echostr"],
        }
        body = {k: v for k, v in params.items() if k not in {"timestamp", "signature_method", "echostr", "sign"}}
        body["sign"] = sign
        return headers, body
