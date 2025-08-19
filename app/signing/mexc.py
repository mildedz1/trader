from __future__ import annotations

import hmac
import hashlib
from dataclasses import dataclass


@dataclass
class MexcSpotSigner:
    secret_key: str

    def sign(self, query_string: str) -> str:
        # Signature is HMAC SHA256 of query string with secret key, hex encoded
        return hmac.new(self.secret_key.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256).hexdigest()

